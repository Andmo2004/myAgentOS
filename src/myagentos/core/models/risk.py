"""Risk model and monotonic escalation logic according to §5."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.errors import RiskMonotonicityViolation


class RiskLevel(StrEnum):
    """Monotonic risk levels defined in §5.1."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        ranks = {
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4,
        }
        return ranks[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank >= other.rank
        return NotImplemented

    def escalate_to(self, new_level: Self) -> Self:
        """Enforces monotonic risk rule: within a job, risk can only increase or stay equal."""
        if new_level < self:
            raise RiskMonotonicityViolation(
                f"Cannot de-escalate risk from {self.value} to {new_level.value}. "
                "Risk within a job is monotonic (§5.1)."
            )
        return new_level


class RiskPhase(StrEnum):
    """The three evaluation phases of risk (§5.1)."""

    PRELIMINARY = "PRELIMINARY"  # Local Router
    FINAL = "FINAL"  # Policy Engine on PLAN_SPEC
    DIFF = "DIFF"  # Policy Engine on PatchSet


class RiskSignal(BaseModel):
    """Specific signal that causes risk escalation (§5.2)."""

    model_config = ConfigDict(frozen=True)

    category: str = Field(..., description="Category (auth, db, infra, ci, secrets, api, test)")
    description: str = Field(..., description="Human readable description of the risk trigger")
    path: str | None = Field(default=None, description="Affected file path if applicable")
    minimum_risk: RiskLevel = Field(
        default=RiskLevel.HIGH,
        description="Minimum risk level triggered by this signal",
    )


class RiskAssessment(BaseModel):
    """Snapshot of a risk assessment at a specific phase."""

    model_config = ConfigDict(frozen=True)

    level: RiskLevel
    phase: RiskPhase
    evaluator: str
    signals: list[RiskSignal] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
