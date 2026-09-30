"""Domain models and structured output schemas for the Planner agent (§7, §8.3)."""

from pydantic import BaseModel, ConfigDict, Field

from myagentos.context.models import CompiledContext


class PlannerInput(BaseModel):
    """Input payload provided to the Planner agent (§8.3)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    task_prompt: str
    context: CompiledContext
    base_commit: str = "HEAD"
    version: int = 1
    feedback: str | None = None


class PlanResponseSchema(BaseModel):
    """Structured response schema expected from the Planner LLM (§8.3)."""

    model_config = ConfigDict(frozen=True)

    files_to_modify: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    files_to_delete: list[str] = Field(default_factory=list)
    altered_interfaces: list[str] = Field(
        default_factory=list,
        description="Public signatures or exports being modified",
    )
    test_specs: list[str] = Field(
        default_factory=list,
        description="Acceptance criteria and specifications for the Test Author (§13.4)",
    )
    preliminary_risk: str = Field(default="LOW")
    risk_reasons: list[str] = Field(default_factory=list)
    permissions_requested: dict[str, list[str]] = Field(default_factory=dict)
    impact_summary: str = Field(default="")
    assumptions: list[str] = Field(default_factory=list)
    data_classification_max: str = Field(default="internal")
    rationale: str = Field(default="")
