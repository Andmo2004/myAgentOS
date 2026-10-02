"""Domain models for Independent Code Review and Diff Approval according to §15."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.patch import PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel


class ReviewVerdict(StrEnum):
    """Verdict rendered by the Independent Reviewer (§15.1)."""

    PASS = "PASS"
    FAIL = "FAIL"


class ReviewSeverity(StrEnum):
    """Severity of individual review comments (§15.1)."""

    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class ReviewComment(BaseModel):
    """Specific observation on a modified file or line (§15.1)."""

    model_config = ConfigDict(frozen=True)

    path: str | None = None
    line: int | None = None
    severity: ReviewSeverity = ReviewSeverity.WARNING
    message: str


class ReviewSpec(BaseModel):
    """Context provided to the Independent Reviewer with strict blindness guarantees (§15.1)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    patch_set: PatchSet
    plan: PlanSpec
    risk_level: RiskLevel
    worker_model_id: str
    reviewer_model: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    """Structured report produced by the Independent Reviewer (§15.1)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    verdict: ReviewVerdict
    passed: bool
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall quality/security score between 0.0 and 1.0",
    )
    summary: str = ""
    comments: list[ReviewComment] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)
    quality_findings: list[str] = Field(default_factory=list)
    diff_hash: str = ""
    reviewed_by: str = "deterministic"
    deterministic_passed: bool = True
    llm_passed: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiffApproval(BaseModel):
    """Versioned human approval tied immutably to a diff hash (§8.4, §15.2, AGF-007)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    diff_hash: str
    approved: bool
    approved_by: str = "user"
    version: int = 1
    feedback: str | None = None
    schema_version: int = 2
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
