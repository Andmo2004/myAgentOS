"""Credential models, statuses, identity profiles, and fingerprinting (§4, §5, §18).

Follows specifications from docs/new_features/agentic-os-feature-model-credentials-discovery.md (AO-MODEL-CREDENTIALS-01).
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CredentialStatus(StrEnum):
    """Normalized credential validation status (§5)."""

    UNKNOWN = "unknown"
    CHECKING = "checking"
    VALID = "valid"
    INVALID = "invalid"
    REVOKED = "revoked"
    EXPIRED = "expired"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


def derive_fingerprint(secret: str | None) -> str:
    """Derives a safe, non-reversible fingerprint from a secret (§18).

    Never exposes the raw secret. Format: ••••<4_hex_digits>
    """
    if not secret or not secret.strip():
        return "••••none"
    digest = hashlib.sha256(secret.strip().encode("utf-8")).hexdigest()
    return f"••••{digest[-4:]}"


class IdentityInfo(BaseModel):
    """Non-secret account and billing metadata exposed by the provider (§4.3, §17, §20).

    Fields are None unless explicitly provided by the provider.
    Never infers local OS user identity.
    """

    model_config = ConfigDict(frozen=True)

    principal_name: str | None = None
    principal_type: str | None = None  # user, account, service_account, workspace
    organization: str | None = None
    project: str | None = None
    workspace: str | None = None
    billing_scope: str | None = None
    quota_scope: str | None = None

    def has_identity(self) -> bool:
        """Returns True if any non-empty identity attribute is present."""
        return any(
            v for k, v in self.__dict__.items() if k != "principal_type" and v is not None
        )

    def describe(self) -> str:
        """Returns a compact readable string representing this identity."""
        parts: list[str] = []
        if self.organization:
            parts.append(f"org:{self.organization}")
        if self.project:
            parts.append(f"proj:{self.project}")
        if self.workspace:
            parts.append(f"workspace:{self.workspace}")
        if self.principal_name:
            parts.append(self.principal_name)
        return " / ".join(parts) if parts else "Not provided by provider"


class CredentialProfile(BaseModel):
    """Non-secret credential profile and lifecycle state (§4.2, §22)."""

    model_config = ConfigDict(frozen=True)

    credential_id: str
    provider: str
    kind: str = "api_key"  # api_key, oauth, local, mock
    source: str = "environment"  # environment, .env, keychain, config
    fingerprint: str = "none"
    status: CredentialStatus = CredentialStatus.UNKNOWN
    last_validated_at: datetime | None = None
    identity: IdentityInfo | None = None
    error_message: str | None = None
