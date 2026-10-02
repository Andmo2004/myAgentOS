"""Model Gateway: single authorized egress point to remote LLM providers (Zone Z2, §17).

Integrates credential validation, account identity, and live model discovery (§6, §8, §9, §14, §15).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.credential_store import CredentialStore
from myagentos.gateway.credentials import (
    CredentialProfile,
    CredentialStatus,
    derive_fingerprint,
)
from myagentos.gateway.discovery import (
    DiscoveredModel,
    DiscoveredModelSet,
    DiscoveryCache,
    EffectiveModelSet,
)
from myagentos.gateway.plan_connection import (
    ConnectionServiceStatus,
    PlanConnectionError,
    PlanConnectionProfile,
    PlanUsageLimitError,
)
from myagentos.gateway.registry import ModelRegistry

KNOWN_PROVIDER_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"],
    "anthropic": [
        "claude-3-5-sonnet-latest",
        "claude-3-5-sonnet",
        "claude-3-5-haiku-latest",
        "claude-3-5-haiku",
    ],
    "google": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    "mock": ["mock-mya", "mock-fast", "mock-reasoning"],
}


class ModelGateway:
    """The Model Gateway regulates all external inference calls in Zone Z2 (§17.1)."""

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        discovery_ttl_seconds: int = 300,
        credential_store: CredentialStore | None = None,
        auto_load_plan_connections: bool = True,
    ) -> None:
        self.registry = registry or ModelRegistry()
        self.adapters: dict[str, ProviderAdapter] = {}
        self._plan_connections: dict[str, PlanConnectionProfile] = {}
        self._plan_adapters: dict[str, ProviderAdapter] = {}
        self.discovery_cache = DiscoveryCache(default_ttl_seconds=discovery_ttl_seconds)
        self._credential_profiles: dict[str, CredentialProfile] = {}
        self.credential_store = credential_store or CredentialStore()
        if auto_load_plan_connections:
            self.load_persisted_connections()

    def _normalize_provider(self, provider: str) -> str:
        p = provider.lower().strip()
        if p == "gemini":
            return "google"
        return p

    def register_adapter(self, provider: str, adapter: ProviderAdapter) -> None:
        norm = self._normalize_provider(provider)
        self.adapters[norm] = adapter
        if norm == "google":
            self.adapters["gemini"] = adapter

    def load_persisted_connections(self) -> None:
        """Loads persisted plan connection profiles and configures adapters (§4, §5)."""
        try:
            for profile in self.credential_store.list_profiles():
                adapter = self._build_plan_adapter(profile)
                if adapter:
                    self.register_plan_connection(profile, adapter, persist=False)
        except Exception:
            pass

    def _build_plan_adapter(self, profile: PlanConnectionProfile) -> ProviderAdapter | None:
        from myagentos.gateway.plan_connection import ConnectionPlatform

        if profile.platform in (ConnectionPlatform.CHATGPT_PLAN, ConnectionPlatform.OPENAI):
            from myagentos.gateway.chatgpt_plan_adapter import ChatGPTPlanAdapter

            return ChatGPTPlanAdapter(connection_profile=profile, store=self.credential_store)
        elif profile.platform in (ConnectionPlatform.CLAUDE, ConnectionPlatform.CLAUDE_CODE):
            from myagentos.gateway.claude_code_adapter import ClaudeCodeAdapter

            return ClaudeCodeAdapter(connection_profile=profile)
        return None

    def register_plan_connection(
        self,
        profile: PlanConnectionProfile,
        adapter: ProviderAdapter,
        persist: bool = True,
    ) -> None:
        """Registers an authenticated plan connection and its dedicated adapter (§4, §5)."""
        self._plan_connections[profile.connection_id] = profile
        self._plan_adapters[profile.connection_id] = adapter
        if persist:
            try:
                self.credential_store.save_profile(profile)
            except Exception:
                pass

    def get_plan_connection(self, connection_id: str) -> PlanConnectionProfile | None:
        """Returns the public connection profile for connection_id."""
        return self._plan_connections.get(connection_id)

    def get_plan_adapter(self, connection_id: str) -> ProviderAdapter | None:
        """Returns the provider adapter bound to connection_id."""
        return self._plan_adapters.get(connection_id)

    def list_plan_connections(self) -> list[PlanConnectionProfile]:
        """Lists all registered plan connection profiles."""
        return list(self._plan_connections.values())

    def remove_plan_connection(
        self, connection_id: str, delete_stored: bool = False
    ) -> bool:
        """Removes a plan connection and its adapter from the gateway."""
        existed = connection_id in self._plan_connections
        self._plan_connections.pop(connection_id, None)
        self._plan_adapters.pop(connection_id, None)
        if delete_stored:
            try:
                self.credential_store.delete_profile(connection_id)
                self.credential_store.delete_credential(connection_id)
            except Exception:
                pass
        return existed

    def discover_plan_models(self, connection_id: str) -> list[DiscoveredModel]:
        """Discovers accessible models from a plan connection catalog (§6)."""
        adapter = self.get_plan_adapter(connection_id)
        if adapter is None:
            raise PlanConnectionError(
                f"No adapter registered for plan connection '{connection_id}'"
            )
        return adapter.discover_models()

    def get_adapter(self, provider: str) -> ProviderAdapter | None:
        norm = self._normalize_provider(provider)
        return self.adapters.get(norm)

    def validate_credential(self, provider: str) -> CredentialProfile:
        """Validates credential using lowest-privilege adapter call (§6, §26)."""
        adapter = self.get_adapter(provider)
        norm_prov = self._normalize_provider(provider)
        if adapter is None:
            profile = CredentialProfile(
                credential_id=f"cred_{norm_prov}",
                provider=norm_prov,
                kind="api_key",
                source="none",
                status=CredentialStatus.UNKNOWN,
                error_message=f"No provider adapter registered for '{provider}'",
            )
            self._credential_profiles[norm_prov] = profile
            return profile

        status, err_msg, identity = adapter.validate_credential()
        raw_key = getattr(adapter, "api_key", "")
        fingerprint = derive_fingerprint(raw_key) if raw_key else "none"

        source = "environment"
        if norm_prov == "mock":
            source = "mock"
        else:
            env_file = Path(".env")
            if env_file.exists():
                try:
                    content = env_file.read_text(encoding="utf-8")
                    if raw_key and raw_key in content:
                        source = ".env"
                except Exception:
                    pass

        profile = CredentialProfile(
            credential_id=f"cred_{norm_prov}",
            provider=norm_prov,
            kind="api_key" if norm_prov != "mock" else "mock",
            source=source,
            fingerprint=fingerprint,
            status=status,
            last_validated_at=datetime.now(UTC),
            identity=identity,
            error_message=err_msg,
        )
        self._credential_profiles[norm_prov] = profile
        if status in (CredentialStatus.INVALID, CredentialStatus.REVOKED):
            self.discovery_cache.invalidate(provider=norm_prov)
        return profile

    def get_credential_profile(
        self, provider: str, validate_if_missing: bool = True
    ) -> CredentialProfile | None:
        norm = self._normalize_provider(provider)
        if norm in self._credential_profiles:
            return self._credential_profiles[norm]
        if validate_if_missing:
            return self.validate_credential(provider)
        return None

    def discover_models(self, provider: str, force_refresh: bool = False) -> DiscoveredModelSet:
        """Discovers accessible models from provider with caching and TTL (§8, §14)."""
        adapter = self.get_adapter(provider)
        norm = self._normalize_provider(provider)
        if adapter is None:
            return DiscoveredModelSet(
                provider=norm,
                credential_id="none",
                models=[],
                discovered_at=datetime.now(UTC),
            )

        raw_key = getattr(adapter, "api_key", "")
        cred_id = derive_fingerprint(raw_key) if raw_key else "default"

        if not force_refresh:
            cached = self.discovery_cache.get(norm, cred_id)
            if cached is not None:
                return cached

        try:
            models = adapter.discover_models()
        except Exception:
            models = []

        return self.discovery_cache.set(norm, cred_id, models)

    def get_effective_model_set(
        self,
        provider: str,
        active_model: str = "",
        force_refresh: bool = False,
    ) -> EffectiveModelSet:
        """Calculates effective usable models: discovered ∩ registry ∩ policy (§9)."""
        norm = self._normalize_provider(provider)
        if force_refresh or norm not in self._credential_profiles:
            profile = self.validate_credential(norm)
        else:
            profile = self._credential_profiles[norm]

        if profile.status in (CredentialStatus.INVALID, CredentialStatus.REVOKED):
            return EffectiveModelSet(
                provider=norm,
                credential_status=profile.status,
                available_models=[],
                restricted_models=KNOWN_PROVIDER_MODELS.get(norm, []),
                policy_filtered_models=[],
                active_model=active_model,
            )

        disc_set = self.discover_models(norm, force_refresh=force_refresh)
        discovered_ids = disc_set.model_ids
        if not discovered_ids and profile.status in (
            CredentialStatus.VALID,
            CredentialStatus.PROVIDER_UNAVAILABLE,
            CredentialStatus.UNKNOWN,
        ):
            discovered_ids = KNOWN_PROVIDER_MODELS.get(norm, [])

        reg_entries = self.registry.get_entries_for_provider(norm)
        if not reg_entries:
            available = discovered_ids
            restricted = []
            policy_filtered = []
        else:
            reg_active = [e.model_id for e in reg_entries if e.lifecycle == "active"]
            reg_retired = [e.model_id for e in reg_entries if e.lifecycle != "active"]

            policy_filtered = [m for m in discovered_ids if m in reg_retired]
            available = [m for m in discovered_ids if m not in reg_retired]
            restricted = [m for m in reg_active if m not in discovered_ids]

        return EffectiveModelSet(
            provider=norm,
            credential_status=profile.status,
            available_models=available,
            restricted_models=restricted,
            policy_filtered_models=policy_filtered,
            active_model=active_model,
        )

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        provider: str | None = None,
        platform: str = "api",
        connection_id: str | None = None,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Dispatches an inference request through the registered provider adapter (§17.1)."""
        # If bound to an explicit plan connection (§4, §7)
        if connection_id:
            plan_adapter = self.get_plan_adapter(connection_id)
            if plan_adapter is None:
                raise PlanConnectionError(
                    f"No active adapter found for connection '{connection_id}'",
                    platform=platform,
                )
            profile = self.get_plan_connection(connection_id)
            if profile and profile.status == ConnectionServiceStatus.QUOTA_EXHAUSTED:
                raise PlanUsageLimitError(
                    f"Connection '{connection_id}' quota is exhausted; new calls are paused.",
                    platform=profile.platform.value,
                    code="quota_exhausted",
                )
            return plan_adapter.generate(
                messages=messages,
                model_id=model_id,
                temperature=temperature,
                response_schema=response_schema,
            )

        resolved_provider = provider

        # Attempt to resolve from registry
        if not resolved_provider:
            for entry in self.registry._entries.values():
                if entry.model_id == model_id:
                    resolved_provider = entry.provider
                    break

        # Fallback heuristic resolution if not explicitly in registry
        if not resolved_provider:
            if model_id.startswith("mock"):
                resolved_provider = "mock"
            elif (
                model_id.startswith("gpt")
                or "openai" in model_id
                or model_id.startswith("o1")
                or model_id.startswith("o3")
            ):
                resolved_provider = "openai"
            elif "gemini" in model_id or "google" in model_id:
                resolved_provider = "google"
            elif "claude" in model_id or "anthropic" in model_id:
                resolved_provider = "anthropic"
            else:
                resolved_provider = "mock"

        adapter = self.get_adapter(resolved_provider)
        if adapter is None:
            msg = f"No provider adapter registered for '{resolved_provider}' (model: {model_id})"
            raise MyAgentOSError(msg)

        try:
            return adapter.generate(
                messages=messages,
                model_id=model_id,
                temperature=temperature,
                response_schema=response_schema,
            )
        except Exception as exc:
            err_str = str(exc).lower()
            if (
                "401" in err_str
                or "403" in err_str
                or "unauthorized" in err_str
                or "forbidden" in err_str
            ):
                self.discovery_cache.invalidate(provider=resolved_provider)
                if resolved_provider in self._credential_profiles:
                    curr = self._credential_profiles[resolved_provider]
                    self._credential_profiles[resolved_provider] = curr.model_copy(
                        update={"status": CredentialStatus.INVALID, "error_message": str(exc)}
                    )
            raise
