"""Domain models and configuration for the end-to-end pipeline orchestrator (§8)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.knowledge import ProjectNote
from myagentos.core.models.patch import PatchSet
from myagentos.core.models.plan import PlanApproval, PlanSpec
from myagentos.core.models.review import DiffApproval, ReviewResult
from myagentos.fsm.states import JobState
from myagentos.verification.guard import VerificationResult


class PipelineConfig(BaseModel):
    """Execution options for an end-to-end task run (§8)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_root: Path
    model_id: str = "mock"
    reviewer_model_id: str | None = None
    curator_model_id: str | None = None
    auto_approve: bool = False
    use_worktree: bool = True
    max_steps: int = 12
    approval_callback: Callable[[str, PlanSpec], bool] | None = None
    diff_approval_callback: Callable[[str, PatchSet], bool] | None = None
    skills_dir: Path | None = None
    explicit_skills: list[str] = Field(default_factory=list)
    verification_profile: Any | None = None
    compile_cmd: str | None = None
    lint_cmd: str | None = None
    test_cmd: str | None = None
    sandbox_driver: Any | None = None
    connection_id: str | None = None


class PipelineResult(BaseModel):
    """Comprehensive result of an end-to-end pipeline execution (§8, §26)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    success: bool
    final_state: JobState
    intent: str
    plan: PlanSpec | None = None
    approval: PlanApproval | None = None
    patch_set: PatchSet | None = None
    verification: VerificationResult | None = None
    review: ReviewResult | None = None
    diff_approval: DiffApproval | None = None
    notes: list[ProjectNote] = Field(default_factory=list)
    audit_events_count: int = 0
    hash_chain_intact: bool = True
    duration_seconds: float = 0.0
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
