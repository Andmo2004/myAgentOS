"""Capability tokens and least-privilege enforcement according to §2, §5.4, §23."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from fnmatch import fnmatch
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.data_policy import TrustTag
from myagentos.core.models.risk import RiskLevel


class NetworkScope(StrEnum):
    """Network egress modes for workers and sandbox (§11.4 & §23)."""

    NONE = "none"  # Default for Code Sandbox Z4
    INTERNAL_ONLY = "internal-only"  # Isolated internal network (test DBs)
    ALLOWLIST = "allowlist"  # Specific proxied endpoints (Research Plane Z3 / exceptional)


class TokenLimits(BaseModel):
    """Hard upper bounds on worker execution (§23)."""

    model_config = ConfigDict(frozen=True)

    max_files: int = Field(default=3, ge=1)
    max_diff_lines: int = Field(default=150, ge=1)
    max_steps: int = Field(default=12, ge=1)


class CapabilityToken(BaseModel):
    """The capability token represents explicit, temporal authority granted to a worker (§23)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    worker_id: str
    risk_level: RiskLevel
    read_scope: list[str] = Field(
        ...,
        description="Glob patterns of files/directories readable in the repository",
    )
    write_scope: list[str] = Field(
        ...,
        description="Glob patterns of files allowed to be modified or created by the patch",
    )
    execute_scope: list[str] = Field(
        default_factory=list,
        description="Exact commands or prefix allowed to be executed in the sandbox",
    )
    network_scope: NetworkScope = Field(default=NetworkScope.NONE)
    limits: TokenLimits = Field(default_factory=TokenLimits)
    trust: TrustTag = Field(default=TrustTag.UNTRUSTED)
    skills: list[str] = Field(default_factory=list)
    base_commit: str = Field(..., description="Commit hash to which this token is strictly bound")
    expires_at: datetime = Field(default_factory=lambda: datetime.now(UTC) + timedelta(minutes=30))

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def is_read_allowed(self, file_path: str) -> bool:
        normalized = file_path.strip("/")
        return any(
            fnmatch(normalized, pattern) or fnmatch(file_path, pattern)
            for pattern in self.read_scope
        )

    def is_write_allowed(self, file_path: str) -> bool:
        normalized = file_path.strip("/")
        return any(
            fnmatch(normalized, pattern) or fnmatch(file_path, pattern)
            for pattern in self.write_scope
        )

    def is_execute_allowed(self, command: str) -> bool:
        trimmed = command.strip()
        return any(
            trimmed == allowed or trimmed.startswith(f"{allowed} ")
            for allowed in self.execute_scope
        )

    def intersect_with(self, other: Self) -> Self:
        """Token intersection rule (§20 & §23): intersection of policy, plan, and skills."""
        # A read path/pattern is kept if it matches both tokens
        read_candidates = set(self.read_scope) | set(other.read_scope)
        common_read = sorted(
            [p for p in read_candidates if self.is_read_allowed(p) and other.is_read_allowed(p)]
        )

        # A write path/pattern is kept if it matches both tokens
        write_candidates = set(self.write_scope) | set(other.write_scope)
        common_write = sorted(
            [p for p in write_candidates if self.is_write_allowed(p) and other.is_write_allowed(p)]
        )

        # Command is kept if both allow execution
        exec_candidates = set(self.execute_scope) | set(other.execute_scope)
        common_exec = sorted(
            [
                cmd
                for cmd in exec_candidates
                if self.is_execute_allowed(cmd) and other.is_execute_allowed(cmd)
            ]
        )

        # Network scope cannot expand: take the most restrictive
        network_order = {
            NetworkScope.NONE: 0,
            NetworkScope.INTERNAL_ONLY: 1,
            NetworkScope.ALLOWLIST: 2,
        }
        restricted_network = (
            self.network_scope
            if network_order[self.network_scope] <= network_order[other.network_scope]
            else other.network_scope
        )

        min_limits = TokenLimits(
            max_files=min(self.limits.max_files, other.limits.max_files),
            max_diff_lines=min(self.limits.max_diff_lines, other.limits.max_diff_lines),
            max_steps=min(self.limits.max_steps, other.limits.max_steps),
        )

        return self.model_copy(
            update={
                "read_scope": common_read,
                "write_scope": common_write,
                "execute_scope": common_exec,
                "network_scope": restricted_network,
                "limits": min_limits,
                "risk_level": max(self.risk_level, other.risk_level),
                "trust": self.trust.combine_with(other.trust),
                "expires_at": min(self.expires_at, other.expires_at),
            }
        )
