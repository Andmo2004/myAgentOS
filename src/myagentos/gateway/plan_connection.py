"""Plan connection models, statuses, and exceptions (§1, §4, §8).

Follows specifications from
docs/new_features/agentic-os-feature-model-plan-connect-v2.md
(AO-MODEL-PLAN-CONNECT-01).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.errors import MyAgentOSError


class ConnectionPlatform(StrEnum):
    """Execution platform for model connections (§1, §4)."""

    CHATGPT_PLAN = "chatgpt_plan"
    CLAUDE_CODE_PLAN = "claude_code_plan"
    OPENAI = "openai"
    CLAUDE = "claude"
    CLAUDE_CODE = "claude_code"
    API = "api"
    MOCK = "mock"


class ConnectionAuthKind(StrEnum):
    """Authentication mechanism governing the connection (§4, §5)."""

    OAUTH = "oauth"
    EXTERNAL_CLI = "external_cli"
    CLI_DELEGATED = "cli_delegated"
    API_KEY = "api_key"


class ConnectionServiceStatus(StrEnum):
    """Service status distinct from credential validity (§4, §8).

    A quota exhaustion condition does NOT invalidate credentials.
    """

    READY = "ready"
    QUOTA_EXHAUSTED = "quota_exhausted"
    USAGE_UNAVAILABLE = "usage_unavailable"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    DISCONNECTED = "disconnected"
    DEGRADED = "degraded"


class PlanConnectionError(MyAgentOSError):
    """Base error for plan connection failures (§9)."""

    def __init__(self, message: str, platform: str | None = None) -> None:
        super().__init__(message)
        self.platform = platform


class PlanAuthenticationError(PlanConnectionError):
    """Raised when authentication, consent, or token verification fails (§5, §9)."""

    def __init__(
        self,
        message: str,
        platform: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message, platform=platform)
        self.error_code = error_code


class PlanUsageLimitError(PlanConnectionError):
    """Raised when plan quota or rate limits are reached (§8, §9).

    Never fabricates USD costs or estimates provider quotas without evidence.
    """

    def __init__(
        self,
        message: str,
        platform: str,
        code: str = "quota_exhausted",
        reset_at: datetime | None = None,
        usage_url: str | None = None,
    ) -> None:
        super().__init__(message, platform=platform)
        self.code = code
        self.reset_at = reset_at
        self.usage_url = usage_url or (
            "https://chatgpt.com/#settings/Usage"
            if platform == ConnectionPlatform.CHATGPT_PLAN.value
            else "https://claude.ai/settings/usage"
        )


class PlanConnectionProfile(BaseModel):
    """Public, non-secret profile of an active plan connection (§4, §5).

    Contains NO tokens, authorization codes, or private credentials.
    Can be safely logged, displayed in UI/CLI, or inspected in audits.
    """

    model_config = ConfigDict(frozen=True)

    connection_id: str = Field(..., description="Unique connection identifier")
    provider: str = Field(..., description="Provider name: openai, anthropic, etc.")
    platform: ConnectionPlatform = Field(..., description="Target plan platform")
    auth_kind: ConnectionAuthKind = Field(..., description="OAuth, external CLI, or API key")
    account_label: str = Field(
        default="unknown",
        description="User-friendly account label (email, account id, or session type)",
    )
    account_id: str | None = Field(default=None, description="Stable account identifier if known")
    client_id_issued: str | None = Field(
        default=None, description="Dynamic client ID issued during OAuth registration"
    )
    status: ConnectionServiceStatus = Field(
        default=ConnectionServiceStatus.READY,
        description="Current service/quota status",
    )
    tier: str = Field(default="pro", description="Subscription tier (plus, pro, team, max)")
    models: list[str] = Field(
        default_factory=list, description="Available models for this connection"
    )
    error_message: str | None = Field(
        default=None, description="Diagnostic error or failure description"
    )
    last_validated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last successful status or token validation",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive metadata (e.g. CLI version, detected capabilities)",
    )

    @property
    def is_usable(self) -> bool:
        """Indicates whether this connection can accept inference requests right now."""
        return self.status == ConnectionServiceStatus.READY
