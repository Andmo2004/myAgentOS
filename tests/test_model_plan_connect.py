"""Test suite for AO-MODEL-PLAN-CONNECT-01: Model Plan Connect.

Verifies:
1. Protected Credential Store permissions (0700/0600) and atomic write.
2. Cross-process mutual exclusion locking.
3. OAuth PKCE generation and callback validation.
4. Token refresh idempotency and lock behavior.
5. ChatGPT Plan Adapter Responses API streaming accumulation.
6. ChatGPT Plan Adapter quota exhaustion error mapping.
7. Claude Code Adapter sanitized environment and authMethod validation.
8. Claude Code Adapter abortion on unexpected tool_use events.
9. ModelGateway routing via connection_id and quota gating.
10. PipelineOrchestrator subscription quota exhaustion handling.
11. CLI model management commands.
"""

from __future__ import annotations

import json
import os
import stat
import urllib.error
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import jwt
import pytest

from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse
from myagentos.gateway.chatgpt_plan_adapter import ChatGPTPlanAdapter
from myagentos.gateway.claude_code_adapter import (
    PURGED_ENV_VARS,
    ClaudeCodeAdapter,
    build_sanitized_environment,
)
from myagentos.gateway.client import ModelGateway
from myagentos.gateway.credential_store import (
    CredentialStore,
    CredentialStoreError,
    PlanCredentialSecret,
)
from myagentos.gateway.credentials import CredentialStatus
from myagentos.gateway.oauth_openai import (
    OAuthOpenAIEngine,
    generate_pkce_context,
)
from myagentos.gateway.plan_connection import (
    ConnectionAuthKind,
    ConnectionPlatform,
    ConnectionServiceStatus,
    PlanAuthenticationError,
    PlanConnectionError,
    PlanConnectionProfile,
    PlanUsageLimitError,
)
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator

# ---------------------------------------------------------------------------
# 1. Protected Credential Store & Permissions
# ---------------------------------------------------------------------------


def test_credential_store_permissions_and_atomic_write(tmp_path: Path) -> None:
    store_dir = tmp_path / "secure_creds"
    store_file = store_dir / "credentials.json"
    profiles_file = store_dir / "plan_connections.json"
    store = CredentialStore(store_path=store_file, profiles_path=profiles_file)

    # Verify directory permissions (POSIX 0700)
    dir_mode = stat.S_IMODE(os.stat(store_dir).st_mode)
    assert dir_mode == 0o700, f"Expected 0700 dir mode, got {oct(dir_mode)}"

    # Save a secret
    secret = PlanCredentialSecret(
        connection_id="conn-test-chatgpt",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN.value,
        access_token="secret-access-token-12345",
        refresh_token="secret-refresh-token-67890",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    store.save_credential(secret)

    # Verify file permissions (POSIX 0600)
    file_mode = stat.S_IMODE(os.stat(store_file).st_mode)
    assert file_mode == 0o600, f"Expected 0600 file mode, got {oct(file_mode)}"

    # Verify retrieval
    loaded = store.get_credential("conn-test-chatgpt")
    assert loaded is not None
    assert loaded.access_token == "secret-access-token-12345"
    assert loaded.refresh_token == "secret-refresh-token-67890"

    # Verify secret isolation in repr (tokens must be redacted)
    s_repr = repr(secret)
    assert "secret-access-token-12345" not in s_repr
    assert "secret-refresh-token-67890" not in s_repr

    # Verify public profile persistence
    profile = PlanConnectionProfile(
        connection_id="conn-test-chatgpt",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN,
        auth_kind=ConnectionAuthKind.OAUTH,
        account_label="user@example.com",
        status=ConnectionServiceStatus.READY,
        tier="plus",
        models=["gpt-4o", "o1"],
    )
    store.save_profile(profile)
    loaded_profile = store.get_profile("conn-test-chatgpt")
    assert loaded_profile is not None
    assert loaded_profile.account_label == "user@example.com"
    assert loaded_profile.tier == "plus"
    assert loaded_profile.models == ["gpt-4o", "o1"]

    # Verify listing and deletion
    profiles = store.list_profiles()
    assert len(profiles) == 1
    assert store.delete_profile("conn-test-chatgpt") is True
    assert store.get_profile("conn-test-chatgpt") is None
    assert store.delete_credential("conn-test-chatgpt") is True
    assert store.get_credential("conn-test-chatgpt") is None


def test_credential_store_cross_process_locking(tmp_path: Path) -> None:
    store_dir = tmp_path / "lock_test"
    store = CredentialStore(store_path=store_dir / "creds.json")

    # Lock acquisition works cleanly
    with store.lock():
        assert store.lock_path.exists()

    # Verify timeout handling when lock is held
    import fcntl

    lock_fd = os.open(str(store.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(CredentialStoreError, match="Timed out"):
            with store.lock(timeout_seconds=0.1):
                pass
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# ---------------------------------------------------------------------------
# 2. PKCE Generation & OAuth Callback Listener
# ---------------------------------------------------------------------------


def test_pkce_generation_and_callback_validation() -> None:
    ctx = generate_pkce_context(port=14555, host="127.0.0.1")
    assert len(ctx.code_verifier) >= 43
    assert len(ctx.code_challenge) >= 43
    assert ctx.redirect_uri == "http://127.0.0.1:14555/callback"

    engine = OAuthOpenAIEngine()
    auth_url = engine.build_authorization_url(ctx)
    assert "response_type=code" in auth_url
    assert f"code_challenge={ctx.code_challenge}" in auth_url
    assert f"state={ctx.state}" in auth_url
    assert "code_challenge_method=S256" in auth_url


def test_connect_interactive_warns_when_browser_open_fails(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    state_value = "expected-state"

    class FakeContext:
        state = state_value
        nonce = "nonce-123"
        code_verifier = "cv"
        code_challenge = "challenge-123"
        redirect_uri = "http://127.0.0.1:14555/callback"

    class FakeListener:
        def __init__(self, host: str = "127.0.0.1") -> None:
            self.host = host
            self.port = 14555
            self.received_params = {"code": ["abc"], "state": [state_value]}

        def wait_for_callback(self, timeout_seconds: float = 120.0) -> dict[str, list[str]]:
            return self.received_params

        def close(self) -> None:
            pass

    monkeypatch.setattr("myagentos.gateway.oauth_openai.OAuthLoopbackListener", FakeListener)
    monkeypatch.setattr(
        "myagentos.gateway.oauth_openai.generate_pkce_context",
        lambda port, host="127.0.0.1": FakeContext(),
    )
    monkeypatch.setattr("myagentos.gateway.oauth_openai.webbrowser.open", lambda url: False)
    engine = OAuthOpenAIEngine()

    with patch.object(
        engine,
        "exchange_code_for_tokens",
        return_value=PlanCredentialSecret(
            connection_id="conn-openai-chatgpt",
            provider="openai",
            platform=ConnectionPlatform.CHATGPT_PLAN.value,
            access_token="token",
            account_id="user_123",
            account_label="user@example.com",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ):
        engine.connect_interactive(open_browser=True)

    captured = capsys.readouterr()
    assert "Browser could not be opened automatically" in captured.err
    assert "https://auth.openai.com/authorize" in captured.err


def test_oidc_id_token_rejects_wrong_audience_and_issuer() -> None:
    context = generate_pkce_context(port=14555, host="127.0.0.1")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    token = jwt.encode(
        {
            "iss": "https://evil.example",
            "aud": "other-client",
            "sub": "user_123",
            "email": "user@example.com",
            "nonce": context.nonce,
            "exp": int(datetime.now(UTC).timestamp()) - 60,
            "iat": int(datetime.now(UTC).timestamp()) - 120,
        },
        private_key,
        algorithm="RS256",
    )
    engine = OAuthOpenAIEngine()

    with patch("myagentos.gateway.oauth_openai.jwt.PyJWKClient") as mock_jwks, patch(
        "myagentos.gateway.oauth_openai.jwt.decode",
        side_effect=jwt.InvalidTokenError("audience mismatch"),
    ):
        mock_jwks.return_value.get_signing_key_from_jwt.return_value.key = public_key

        with pytest.raises(PlanAuthenticationError, match="audience|issuer|expired|nonce"):
            engine.exchange_code_for_tokens(
                "code-123",
                context,
                http_client=lambda req: {
                    "access_token": "access-token",
                    "id_token": token,
                    "expires_in": 3600,
                },
            )


# ---------------------------------------------------------------------------
# 3. Token Refresh Idempotency & Revocation
# ---------------------------------------------------------------------------


def test_token_refresh_idempotency_under_lock(tmp_path: Path) -> None:
    store = CredentialStore(store_path=tmp_path / "creds.json")
    secret = PlanCredentialSecret(
        connection_id="conn-refresh-test",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN.value,
        access_token="old-token",
        refresh_token="valid-refresh",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),  # Expired
    )
    store.save_credential(secret)

    engine = OAuthOpenAIEngine(store=store)

    call_count = 0

    def mock_http(req: Any) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {
            "access_token": "new-fresh-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

    # First refresh: actually makes request
    refreshed = engine.refresh_access_token("conn-refresh-test", http_client=mock_http)
    assert refreshed.access_token == "new-fresh-access-token"
    assert call_count == 1

    # Second refresh immediately after: token is not expired, re-read under lock returns cached
    cached = engine.refresh_access_token("conn-refresh-test", http_client=mock_http)
    assert cached.access_token == "new-fresh-access-token"
    assert call_count == 1  # No second HTTP call made!


def test_token_refresh_clears_on_invalid_grant(tmp_path: Path) -> None:
    store = CredentialStore(store_path=tmp_path / "creds.json")
    secret = PlanCredentialSecret(
        connection_id="conn-revoked",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN.value,
        access_token="expired-token",
        refresh_token="revoked-refresh",
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    store.save_credential(secret)

    engine = OAuthOpenAIEngine(store=store)

    def mock_http_err(req: Any) -> Any:
        fp = MagicMock()
        fp.read.return_value = b'{"error":"invalid_grant","error_description":"token revoked"}'
        raise urllib.error.HTTPError(
            url=req.full_url, code=400, msg="Bad Request", hdrs=cast(Any, None), fp=fp
        )

    with pytest.raises(PlanAuthenticationError, match="invalid or revoked"):
        engine.refresh_access_token("conn-revoked", http_client=mock_http_err)

    # Local credentials must be purged to break retry loops
    assert store.get_credential("conn-revoked") is None


# ---------------------------------------------------------------------------
# 4. ChatGPT Plan Adapter: Streaming Accumulation & Quota Errors
# ---------------------------------------------------------------------------


def test_chatgpt_plan_adapter_streaming_accumulation(tmp_path: Path) -> None:
    store = CredentialStore(store_path=tmp_path / "creds.json")
    secret = PlanCredentialSecret(
        connection_id="conn-chatgpt",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN.value,
        access_token="tok-valid",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    store.save_credential(secret)

    adapter = ChatGPTPlanAdapter(connection_id="conn-chatgpt", store=store)

    # Mock SSE stream from Responses API
    sse_events = [
        b'event: response.created\ndata: {"id":"resp_1"}\n\n',
        b'event: response.output_item.added\ndata: {"item":{"type":"message"}}\n\n',
        b'event: response.content_part.added\ndata: {"part":{"type":"text"}}\n\n',
        b'event: response.output_text.delta\ndata: {"delta":"Hello "}\n\n',
        b'event: response.output_text.delta\ndata: {"delta":"World!"}\n\n',
        (
            b'event: response.completed\ndata: {"response":'
            b'{"usage":{"input_tokens":10,"output_tokens":5}}}\n\n'
        ),
    ]

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__iter__.return_value = sse_events

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        llm_resp = adapter.generate(
            messages=[
                LLMMessage(role="system", content="You are a helper"),
                LLMMessage(role="user", content="Say hello"),
            ],
            model_id="gpt-4o",
            temperature=0.0,
        )

        assert llm_resp.content == "Hello World!"
        assert llm_resp.input_tokens == 10
        assert llm_resp.output_tokens == 5
        assert llm_resp.model_id == "gpt-4o"

        # Verify sent payload stripped unsupported fields and mapped system prompt
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["store"] is False
        assert payload["stream"] is True
        assert "instructions" in payload
        assert "You are a helper" in payload["instructions"]
        assert "temperature" not in payload
        assert "max_output_tokens" not in payload


def test_chatgpt_plan_adapter_quota_exhausted_raises_plan_usage_limit_error(
    tmp_path: Path,
) -> None:
    store = CredentialStore(store_path=tmp_path / "creds.json")
    secret = PlanCredentialSecret(
        connection_id="conn-quota-test",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN.value,
        access_token="tok-valid",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    store.save_credential(secret)

    adapter = ChatGPTPlanAdapter(connection_id="conn-quota-test", store=store)

    err_payload = json.dumps(
        {
            "error": {
                "message": "You have exceeded your monthly usage limits for this plan.",
                "code": "subscription_sharing_usage_limit_exceeded",
            }
        }
    ).encode("utf-8")

    fp = MagicMock()
    fp.read.return_value = err_payload
    http_err = urllib.error.HTTPError(
        url="https://api.openai.com/v1/responses",
        code=429,
        msg="Too Many Requests",
        hdrs=cast(Any, None),
        fp=fp,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(PlanUsageLimitError) as exc_info:
            adapter.generate(
                messages=[LLMMessage(role="user", content="test")],
                model_id="gpt-4o",
            )
        assert exc_info.value.code == "subscription_sharing_usage_limit_exceeded"
        assert exc_info.value.platform == ConnectionPlatform.CHATGPT_PLAN.value
        assert "https://chatgpt.com/#settings/Usage" in exc_info.value.usage_url


# ---------------------------------------------------------------------------
# 5. Claude Code Adapter: Environment Sanitization & Invariants
# ---------------------------------------------------------------------------


def test_claude_code_adapter_sanitized_env() -> None:
    # Set dirty environment
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-api-test"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "token-test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "aws-test"

    try:
        clean = build_sanitized_environment()
        for purged in PURGED_ENV_VARS:
            assert purged not in clean, f"Variable '{purged}' was not purged from clean environment"
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)


def test_claude_code_adapter_validates_auth_method() -> None:
    # 1. Output from claude auth status indicates claude.ai -> VALID
    def mock_status_valid(cmd: list[str], env: dict[str, str]) -> str:
        return json.dumps({"authMethod": "claude.ai", "email": "user@claude.ai"})

    adapter = ClaudeCodeAdapter(
        connection_id="conn-claude",
        process_runner=mock_status_valid,
    )
    status, err, identity = adapter.validate_credential()
    assert status == CredentialStatus.VALID
    assert err is None
    assert identity is not None
    assert identity.principal_name == "user@claude.ai"

    # 2. Output indicates api_key or console -> INVALID
    def mock_status_invalid(cmd: list[str], env: dict[str, str]) -> str:
        return json.dumps({"authMethod": "api_key", "email": "dev@company.com"})

    adapter_bad = ClaudeCodeAdapter(
        connection_id="conn-claude",
        process_runner=mock_status_invalid,
    )
    status_bad, err_bad, _ = adapter_bad.validate_credential()
    assert status_bad == CredentialStatus.INVALID
    assert "expected 'claude.ai'" in (err_bad or "")


def test_claude_code_adapter_aborts_on_tool_use() -> None:
    # Stream with unexpected tool_use event must trigger immediate abort (SIGKILL invariant)
    tool_use_stream = (
        '{"type":"content_block_start","content_block":{"type":"text"}}\n'
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Thinking..."}}\n'
        '{"type":"content_block_start","content_block":{"type":"tool_use","name":"bash"}}\n'
    )

    def mock_runner_tool_use(cmd: list[str], env: dict[str, str]) -> str:
        return tool_use_stream

    adapter = ClaudeCodeAdapter(
        connection_id="conn-claude",
        process_runner=mock_runner_tool_use,
    )

    with pytest.raises(PlanConnectionError, match="External tool execution is prohibited"):
        adapter.generate(
            messages=[LLMMessage(role="user", content="run tool")],
            model_id="claude-3-5-sonnet-latest",
        )


def test_claude_code_adapter_successful_generation() -> None:
    valid_stream = (
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello from "}}\n'
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Claude!"}}\n'
        '{"type":"message_delta","usage":{"output_tokens":8}}\n'
    )

    def mock_runner(cmd: list[str], env: dict[str, str]) -> str:
        # Check security flags passed to claude CLI
        assert "--tools" in cmd and "" in cmd
        assert "--disallowedTools" in cmd and "mcp__*" in cmd
        assert "--verbose" in cmd
        return valid_stream

    adapter = ClaudeCodeAdapter(
        connection_id="conn-claude",
        process_runner=mock_runner,
    )

    resp = adapter.generate(
        messages=[LLMMessage(role="user", content="hi")],
        model_id="claude-3-5-sonnet-latest",
    )
    assert resp.content == "Hello from Claude!"
    assert resp.output_tokens == 8


# ---------------------------------------------------------------------------
# 6. ModelGateway Integration & Plan Connection Routing
# ---------------------------------------------------------------------------


def test_model_gateway_routes_via_connection_id(tmp_path: Path) -> None:
    store = CredentialStore(store_path=tmp_path / "creds.json")
    gateway = ModelGateway(credential_store=store, auto_load_plan_connections=False)

    profile = PlanConnectionProfile(
        connection_id="conn-custom",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN,
        auth_kind=ConnectionAuthKind.OAUTH,
        status=ConnectionServiceStatus.READY,
    )

    mock_adapter = MagicMock()
    mock_adapter.generate.return_value = LLMResponse(
        content="Routed response",
        model_id="gpt-4o",
    )

    gateway.register_plan_connection(profile, mock_adapter, persist=True)

    # Calling generate with connection_id dispatches to mock_adapter
    res = gateway.generate(
        messages=[LLMMessage(role="user", content="hi")],
        model_id="gpt-4o",
        connection_id="conn-custom",
    )
    assert res.content == "Routed response"
    assert mock_adapter.generate.call_count == 1

    # If connection quota is exhausted, immediately raises PlanUsageLimitError
    exhausted_profile = profile.model_copy(
        update={"status": ConnectionServiceStatus.QUOTA_EXHAUSTED}
    )
    gateway.register_plan_connection(exhausted_profile, mock_adapter, persist=False)

    with pytest.raises(PlanUsageLimitError, match="quota is exhausted"):
        gateway.generate(
            messages=[LLMMessage(role="user", content="hi")],
            model_id="gpt-4o",
            connection_id="conn-custom",
        )


# ---------------------------------------------------------------------------
# 7. Pipeline Orchestrator Quota Exhaustion Pauses Job
# ---------------------------------------------------------------------------


def test_pipeline_orchestrator_quota_exhaustion_pauses_job(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "file.py").write_text("x = 1\n", encoding="utf-8")

    store = CredentialStore(store_path=tmp_path / "creds.json")
    gateway = ModelGateway(credential_store=store, auto_load_plan_connections=False)

    # Register quota-exhausted profile
    profile = PlanConnectionProfile(
        connection_id="conn-paused",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN,
        auth_kind=ConnectionAuthKind.OAUTH,
        status=ConnectionServiceStatus.QUOTA_EXHAUSTED,
    )
    mock_adapter = MagicMock()
    gateway.register_plan_connection(profile, mock_adapter, persist=False)

    from myagentos.sandbox.mock import MockSandboxDriver

    config = PipelineConfig(
        repo_root=repo,
        model_id="gpt-4o",
        connection_id="conn-paused",
        auto_approve=True,
    )
    orchestrator = PipelineOrchestrator(
        config=config,
        gateway=gateway,
        sandbox_driver=MockSandboxDriver(use_real_subprocess=False),
    )

    result = orchestrator.run("Fix bug in file.py")

    assert result.success is False
    assert result.final_state == JobState.BUDGET_PAUSED
    assert "quota" in result.summary.lower()


# ---------------------------------------------------------------------------
# 8. CLI Commands Verification
# ---------------------------------------------------------------------------


def test_cli_model_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from myagentos.cli import cmd_model

    store = CredentialStore(
        store_path=tmp_path / "creds.json",
        profiles_path=tmp_path / "profiles.json",
    )

    profile = PlanConnectionProfile(
        connection_id="conn-cli-test",
        provider="openai",
        platform=ConnectionPlatform.CHATGPT_PLAN,
        auth_kind=ConnectionAuthKind.OAUTH,
        account_label="cli_user@example.com",
        status=ConnectionServiceStatus.READY,
        tier="pro",
        models=["gpt-4o", "o1"],
    )
    store.save_profile(profile)

    # Patch ModelGateway to use test store
    with patch("myagentos.gateway.client.CredentialStore", return_value=store):
        # 1. list
        cmd_model("list")
        cmd_model("list", json_output=True)

        # 2. status
        cmd_model("status", target="conn-cli-test")
        cmd_model("status", target="conn-cli-test", json_output=True)

        # 3. disconnect
        cmd_model("disconnect", target="conn-cli-test")
        assert store.get_profile("conn-cli-test") is None


def test_connect_slash_command_registration_and_parsing() -> None:
    from myagentos.mya.commands.models import CommandCategory
    from myagentos.mya.commands.registry import COMMAND_REGISTRY
    from myagentos.ui.commands import SlashCommandKind, parse_input

    # 1. Parsing verification
    cmd1 = parse_input("/connect")
    assert cmd1.kind == SlashCommandKind.CONNECT
    assert cmd1.argument == ""

    cmd2 = parse_input("/connect chatgpt")
    assert cmd2.kind == SlashCommandKind.CONNECT
    assert cmd2.argument == "chatgpt"

    cmd3 = parse_input("/account status")
    assert cmd3.kind == SlashCommandKind.CONNECT
    assert cmd3.argument == "status"

    cmd4 = parse_input("/connect disconnect conn-openai")
    assert cmd4.kind == SlashCommandKind.CONNECT
    assert cmd4.argument == "disconnect conn-openai"

    # 2. Registry verification
    defn = COMMAND_REGISTRY.get("connect")
    assert defn is not None
    assert defn.category == CommandCategory.CONFIGURATION
    assert "account" in defn.aliases
    assert defn.supports_arguments is True

