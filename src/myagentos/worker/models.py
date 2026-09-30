"""Domain models for Worker execution and Tool Broker mediation (§10)."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from myagentos.core.models.patch import PatchOperation, PatchSet


class WorkerMode(StrEnum):
    """Execution modes for the Worker (§10.2)."""

    SINGLE_SHOT = "SINGLE_SHOT"
    TOOL_LOOP = "TOOL_LOOP"


class ToolStatus(StrEnum):
    """Result status of a mediated tool execution (§10.3)."""

    SUCCESS = "SUCCESS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ERROR = "ERROR"


class ToolCall(BaseModel):
    """A tool invocation proposed by the Worker (§10.3)."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result of a tool execution, always marked UNTRUSTED (§10.3, §18)."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    status: ToolStatus
    output: str
    trust_tag: str = "UNTRUSTED"
    error: str | None = None


class FileEditProposal(BaseModel):
    """Single file modification proposed by the worker."""

    model_config = ConfigDict(frozen=True)

    path: str
    operation: PatchOperation = PatchOperation.MODIFY
    content: str
    old_path: str | None = None

    @field_validator("operation", mode="before")
    @classmethod
    def normalize_operation(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower in [op.value for op in PatchOperation]:
                return PatchOperation(v_lower)
        return v


class PatchProposal(BaseModel):
    """Complete patch proposal payload submitted via propose_patch (§10.4)."""

    model_config = ConfigDict(frozen=True)

    description: str
    files: list[FileEditProposal] = Field(default_factory=list)


class WorkerStep(BaseModel):
    """A single iteration record within the bounded Worker loop (§10.3)."""

    model_config = ConfigDict(frozen=True)

    step_index: int
    thought: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    duration_ms: int = 0


class WorkerResult(BaseModel):
    """Final outcome of the Worker execution (§10.3, §10.4)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    success: bool
    patch_set: PatchSet | None = None
    steps: list[WorkerStep] = Field(default_factory=list)
    total_steps: int = 0
    stop_reason: str  # PROPOSE_PATCH, MAX_STEPS, TIMEOUT, BUDGET_EXCEEDED, ERROR
