"""Live model discovery, cache, and effective model set calculation (§8, §9, §14, §15).

Follows specifications from docs/new_features/agentic-os-feature-model-credentials-discovery.md (AO-MODEL-CREDENTIALS-01).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.gateway.credentials import CredentialStatus


class DiscoveredModel(BaseModel):
    """Metadata for an accessible model returned by provider discovery (§8)."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    provider: str
    display_name: str | None = None
    created_at: int | str | None = None
    owned_by: str | None = None
    raw_capabilities: list[str] = Field(default_factory=list)


class DiscoveredModelSet(BaseModel):
    """Live models accessible with an authenticated credential (§8, §14)."""

    model_config = ConfigDict(frozen=True)

    provider: str
    credential_id: str
    models: list[DiscoveredModel]
    discovered_at: datetime
    ttl_seconds: int = 300

    @property
    def is_expired(self) -> bool:
        """Checks if the cached discovery result has exceeded its TTL (§14)."""
        now = datetime.now(timezone.utc)
        discovered = (
            self.discovered_at
            if self.discovered_at.tzinfo
            else self.discovered_at.replace(tzinfo=timezone.utc)
        )
        age = (now - discovered).total_seconds()
        return age >= self.ttl_seconds

    @property
    def model_ids(self) -> list[str]:
        return [m.model_id for m in self.models]


class EffectiveModelSet(BaseModel):
    """Reconciled set of usable models after registry and policy filtering (§9, §28).

    effective_models =
        discovered_models
        ∩ registry_models (or verified provider models)
        ∩ policy_allowed
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    credential_status: CredentialStatus
    available_models: list[str] = Field(default_factory=list)
    restricted_models: list[str] = Field(default_factory=list)
    policy_filtered_models: list[str] = Field(default_factory=list)
    active_model: str = ""

    def is_available(self, model_id: str) -> bool:
        """Determines if a model can be selected and executed (§12)."""
        return model_id.strip() in self.available_models


class DiscoveryCache:
    """In-memory cache for live discovery results with TTL and invalidation hooks (§14, §15)."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._cache: dict[tuple[str, str], DiscoveredModelSet] = {}

    def get(self, provider: str, credential_id: str) -> DiscoveredModelSet | None:
        """Returns cached discovery set if present and not expired."""
        key = (provider.lower().strip(), credential_id.strip())
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            del self._cache[key]
            return None
        return entry

    def set(
        self,
        provider: str,
        credential_id: str,
        models: list[DiscoveredModel],
        ttl_seconds: int | None = None,
    ) -> DiscoveredModelSet:
        """Caches discovered models for a given provider and credential."""
        key = (provider.lower().strip(), credential_id.strip())
        now = datetime.now(timezone.utc)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        entry = DiscoveredModelSet(
            provider=provider.lower().strip(),
            credential_id=credential_id.strip(),
            models=models,
            discovered_at=now,
            ttl_seconds=ttl,
        )
        self._cache[key] = entry
        return entry

    def invalidate(
        self, provider: str | None = None, credential_id: str | None = None
    ) -> None:
        """Invalidates discovery entries for a provider, credential, or both (§15)."""
        if provider is None and credential_id is None:
            self.clear()
            return

        p = provider.lower().strip() if provider else None
        c = credential_id.strip() if credential_id else None

        keys_to_delete = [
            k for k in self._cache.keys()
            if (p is None or k[0] == p) and (c is None or k[1] == c)
        ]
        for k in keys_to_delete:
            self._cache.pop(k, None)

    def clear(self) -> None:
        """Clears all discovery cache entries."""
        self._cache.clear()
