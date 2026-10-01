"""Comprehensive unit and integration tests for AO-MODEL-CREDENTIALS-01.

Validates:
- Credential validation and fingerprint generation
- Non-secret account identity representation
- Live model discovery and DiscoveryCache with TTL and invalidation
- EffectiveModelSet reconciliation (discovered ∩ registry ∩ policy)
- /model, /model refresh, /model <query>, and guarded /model <id>
- /info non-secret credential and usage presentation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest.mock import MagicMock

import pytest

from myagentos.gateway import (
    CredentialProfile,
    CredentialStatus,
    DiscoveredModel,
    DiscoveredModelSet,
    DiscoveryCache,
    EffectiveModelSet,
    IdentityInfo,
    LLMMessage,
    MockProviderAdapter,
    ModelEntry,
    ModelGateway,
    ModelRegistry,
    derive_fingerprint,
)
from myagentos.gateway.claude_adapter import ClaudeAdapter
from myagentos.gateway.gemini_adapter import GeminiAdapter
from myagentos.gateway.openai_adapter import OpenAIAdapter
from myagentos.mya.commands.observability import ObservabilityService
from myagentos.ui.app import MyaApp


# ============================================================================
# 1. Fingerprint & Credentials Tests
# ============================================================================

def test_derive_fingerprint_deterministic_and_safe() -> None:
    secret = "sk-proj-supersecretkey1234567890"
    fp1 = derive_fingerprint(secret)
    fp2 = derive_fingerprint(secret)

    assert fp1 == fp2
    assert fp1.startswith("••••")
    assert len(fp1) == 8  # 4 bullets + 4 hex chars
    # Ensure raw secret is never present in fingerprint
    assert "supersecret" not in fp1
    assert "sk-proj" not in fp1

    # Empty or short secrets
    assert derive_fingerprint("") == "••••none"
    assert derive_fingerprint("   ") == "••••none"


def test_credential_profile_and_identity_models() -> None:
    identity = IdentityInfo(
        principal_name="api_user",
        organization="Acme AI",
        project="prod-agents",
        quota_scope="prod-agents",
    )
    profile = CredentialProfile(
        credential_id="cred_openai",
        provider="openai",
        kind="api_key",
        source="environment",
        fingerprint="••••a8f2",
        status=CredentialStatus.VALID,
        identity=identity,
    )
    assert profile.status == CredentialStatus.VALID
    assert profile.identity is not None
    assert profile.identity.organization == "Acme AI"
    assert profile.identity.project == "prod-agents"


# ============================================================================
# 2. DiscoveryCache & EffectiveModelSet Tests
# ============================================================================

def test_discovery_cache_ttl_and_invalidation() -> None:
    cache = DiscoveryCache(default_ttl_seconds=300)
    models = [
        DiscoveredModel(model_id="gpt-4o", provider="openai"),
        DiscoveredModel(model_id="gpt-4o-mini", provider="openai"),
    ]

    # Set cache
    entry = cache.set("openai", "••••1234", models, ttl_seconds=2)
    assert len(entry.models) == 2
    assert not entry.is_expired

    # Retrieve cached
    cached = cache.get("openai", "••••1234")
    assert cached is not None
    assert cached.model_ids == ["gpt-4o", "gpt-4o-mini"]

    # Invalidate specific
    cache.invalidate(provider="openai", credential_id="••••1234")
    assert cache.get("openai", "••••1234") is None

    # Test expiration
    entry_short = cache.set("mock", "cred_mock", models, ttl_seconds=-1)
    assert entry_short.is_expired
    assert cache.get("mock", "cred_mock") is None


def test_effective_model_set_availability() -> None:
    effective = EffectiveModelSet(
        provider="openai",
        credential_status=CredentialStatus.VALID,
        available_models=["gpt-4o", "gpt-4o-mini"],
        restricted_models=["o1"],
        policy_filtered_models=["gpt-3.5-turbo"],
        active_model="gpt-4o",
    )
    assert effective.is_available("gpt-4o")
    assert effective.is_available("gpt-4o-mini")
    assert not effective.is_available("o1")
    assert not effective.is_available("gpt-3.5-turbo")
    assert not effective.is_available("non-existent")


# ============================================================================
# 3. Provider Adapters Tests (Mock, OpenAI, Claude, Gemini)
# ============================================================================

def test_mock_adapter_validation_and_discovery() -> None:
    adapter = MockProviderAdapter()
    status, err, identity = adapter.validate_credential()
    assert status == CredentialStatus.VALID
    assert err is None
    assert identity is not None
    assert identity.organization == "mock-org"

    models = adapter.discover_models()
    model_ids = [m.model_id for m in models]
    assert "mock-mya" in model_ids
    assert "mock-fast" in model_ids
    assert "mock-reasoning" in model_ids


def test_openai_adapter_validation_and_discovery_mocked() -> None:
    mock_client = MagicMock()
    # Mock models.list()
    mock_model1 = MagicMock()
    mock_model1.id = "gpt-4o"
    mock_model1.created = 1715000000
    mock_model1.owned_by = "openai"

    mock_model2 = MagicMock()
    mock_model2.id = "text-embedding-3-small"
    mock_model2.created = 1715000000
    mock_model2.owned_by = "openai"

    mock_client.models.list.return_value = [mock_model1, mock_model2]
    mock_client.organization = "org-test1234"
    mock_client.project = "proj-test5678"

    adapter = OpenAIAdapter(api_key="sk-test-key", client=mock_client)
    status, err, identity = adapter.validate_credential()
    assert status == CredentialStatus.VALID
    assert err is None
    assert identity is not None
    assert identity.organization == "org-test1234"
    assert identity.project == "proj-test5678"

    discovered = adapter.discover_models()
    assert len(discovered) == 2
    assert discovered[0].model_id == "gpt-4o"
    assert "tool_use" in discovered[0].raw_capabilities


def test_openai_adapter_validation_error_mapping() -> None:
    mock_client = MagicMock()
    mock_client.models.list.side_effect = Exception("401 Unauthorized: Invalid API key")
    adapter = OpenAIAdapter(api_key="sk-bad-key", client=mock_client)

    status, err, identity = adapter.validate_credential()
    assert status == CredentialStatus.INVALID
    assert err is not None
    assert identity is None


def test_claude_adapter_validation_and_discovery_mocked() -> None:
    mock_client = MagicMock()
    mock_model = MagicMock()
    mock_model.id = "claude-3-5-sonnet-20241022"
    mock_model.display_name = "Claude 3.5 Sonnet"
    mock_model.created_at = datetime.now(timezone.utc)

    mock_page = MagicMock()
    mock_page.data = [mock_model]
    mock_client.models.list.return_value = mock_page

    adapter = ClaudeAdapter(api_key="sk-ant-test", client=mock_client)
    status, err, identity = adapter.validate_credential()
    assert status == CredentialStatus.VALID
    assert identity is None  # Anthropic does not expose org on client

    discovered = adapter.discover_models()
    assert len(discovered) == 1
    assert discovered[0].model_id == "claude-3-5-sonnet-20241022"
    assert discovered[0].provider == "anthropic"


def test_gemini_adapter_validation_and_discovery_mocked() -> None:
    mock_client = MagicMock()
    mock_model = MagicMock()
    mock_model.name = "models/gemini-2.0-flash"
    mock_model.display_name = "Gemini 2.0 Flash"
    mock_client.models.list.return_value = [mock_model]

    adapter = GeminiAdapter(api_key="AIzaSyTest", client=mock_client)
    status, err, identity = adapter.validate_credential()
    assert status == CredentialStatus.VALID

    discovered = adapter.discover_models()
    assert len(discovered) == 1
    assert discovered[0].model_id == "gemini-2.0-flash"
    assert "tool_use" in discovered[0].raw_capabilities


# ============================================================================
# 4. ModelGateway Reconciliation & Cache Invalidation Tests
# ============================================================================

def test_gateway_effective_model_set_reconciliation() -> None:
    registry = ModelRegistry()
    registry.register(
        ModelEntry(
            provider="mock",
            platform="api",
            model_id="mock-mya",
            capabilities=["code_generation"],
            lifecycle="active",
        )
    )
    registry.register(
        ModelEntry(
            provider="mock",
            platform="api",
            model_id="mock-retired",
            capabilities=["code_generation"],
            lifecycle="retired",
        )
    )

    mock_adapter = MockProviderAdapter()
    # Mock adapter discovers mock-mya, mock-fast, mock-reasoning, mock-retired
    mock_adapter.discover_models = MagicMock(
        return_value=[
            DiscoveredModel(model_id="mock-mya", provider="mock"),
            DiscoveredModel(model_id="mock-fast", provider="mock"),
            DiscoveredModel(model_id="mock-retired", provider="mock"),
        ]
    )

    gateway = ModelGateway(registry=registry)
    gateway.register_adapter("mock", mock_adapter)

    effective = gateway.get_effective_model_set("mock", active_model="mock-mya")
    assert effective.credential_status == CredentialStatus.VALID
    assert "mock-mya" in effective.available_models
    assert "mock-fast" in effective.available_models
    # Retired model should be filtered out by policy
    assert "mock-retired" not in effective.available_models
    assert "mock-retired" in effective.policy_filtered_models


def test_gateway_invalid_credential_sets_empty_available() -> None:
    mock_adapter = MockProviderAdapter()
    mock_adapter.validate_credential = MagicMock(
        return_value=(CredentialStatus.INVALID, "Invalid key", None)
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", mock_adapter)

    effective = gateway.get_effective_model_set("mock")
    assert effective.credential_status == CredentialStatus.INVALID
    assert effective.available_models == []


def test_gateway_auto_invalidates_cache_on_401() -> None:
    mock_adapter = MockProviderAdapter()
    mock_adapter.generate = MagicMock(side_effect=Exception("401 Unauthorized API key"))

    gateway = ModelGateway()
    gateway.register_adapter("mock", mock_adapter)
    # Populate cache
    gateway.discovery_cache.set(
        "mock", "cred_mock", [DiscoveredModel(model_id="mock-mya", provider="mock")]
    )
    assert gateway.discovery_cache.get("mock", "cred_mock") is not None

    with pytest.raises(Exception, match="401"):
        gateway.generate(
            messages=[LLMMessage(role="user", content="hello")],
            model_id="mock-mya",
            provider="mock",
        )

    # Discovery cache for mock must be invalidated
    assert gateway.discovery_cache.get("mock", "cred_mock") is None


# ============================================================================
# 5. /info Observability Service Tests
# ============================================================================

def test_observability_render_info_with_credential_metadata() -> None:
    gateway = ModelGateway()
    adapter = MockProviderAdapter()
    gateway.register_adapter("mock", adapter)

    obs = ObservabilityService()
    info_text = obs.render_info(gateway=gateway, model_id="mock-mya")

    assert "SESSION INFORMATION" in info_text
    assert "MYA & MODEL" in info_text
    assert "CREDENTIAL" in info_text
    assert "✓ VALID" in info_text
    assert "Fingerprint:" in info_text
    assert "Account:     mock-org" in info_text
    # Secret must never appear
    assert "api_key" not in info_text.lower() or "not provided" in info_text.lower()


def test_observability_render_info_no_identity_inferred() -> None:
    # When provider exposes no identity, never infer OS username
    mock_adapter = MockProviderAdapter()
    mock_adapter.validate_credential = MagicMock(
        return_value=(CredentialStatus.VALID, None, None)
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", mock_adapter)

    obs = ObservabilityService()
    info_text = obs.render_info(gateway=gateway, model_id="mock-mya")

    assert "Identity:    Not provided by provider" in info_text


# ============================================================================
# 6. UI Commands (/model, /model refresh, /model <query>, /key) Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ui_model_and_discovery_commands() -> None:
    temp_dir = Path(tempfile.mkdtemp())
    app = MyaApp(repo_path=temp_dir, check_first_run=False)

    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input")

        # 1. /model with no args: should display available models and credential
        inp.value = "/model"
        await pilot.press("enter")
        await pilot.pause()

        # 2. /model refresh: should refresh and output counts
        inp.value = "/model refresh"
        await pilot.press("enter")
        await pilot.pause()

        # 3. /model <query>: should filter models
        inp.value = "/model fast"
        await pilot.press("enter")
        await pilot.pause()

        # 4. /model <valid_id>: should switch model
        inp.value = "/model mock-fast"
        await pilot.press("enter")
        await pilot.pause()
        assert app.mya_agent.model_id == "mock-fast"

        # 5. /model <unknown/unavailable_id>: should show not found or guarded refusal
        inp.value = "/model completely-unknown-xyz"
        await pilot.press("enter")
        await pilot.pause()
        # Model should NOT change
        assert app.mya_agent.model_id == "mock-fast"
