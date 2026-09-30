"""Visual state and View Models for the presentation layer (§9).

The UI is a derived projection of the Event Store (§4.1).
View models contain presentation-ready structures without business authority.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.ui.theme.symbols import (
    FileActivityState,
    VisualStatus,
)


class VisualState(BaseModel):
    """Normalized visual state representation for textual rendering (§9)."""

    model_config = ConfigDict(frozen=True)

    status: VisualStatus = VisualStatus.IDLE
    symbol: str = "○"
    emphasis: str = "normal"  # "normal" | "active" | "dim" | "warning" | "error"
    animation: str = "none"  # "none" | "spinner" | "pulse" | "progress"
    label: str = ""


class JobViewModel(BaseModel):
    """View model for live job monitoring (§6.3, §9)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    title: str = ""
    status: VisualStatus = VisualStatus.IDLE
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    steps_completed: int = 0
    steps_total: int = 0
    risk: str = "LOW"


class AgentViewModel(BaseModel):
    """View model representing an agent in the execution tree (§12)."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    role: str
    display_name: str
    status: VisualStatus = VisualStatus.IDLE
    current_activity: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    files: list[str] = Field(default_factory=list)


class FileActivityViewModel(BaseModel):
    """View model representing a single file in the activity monitor (§11)."""

    model_config = ConfigDict(frozen=True)

    file_path: str
    state: FileActivityState = FileActivityState.READ
    agent_id: str = ""
    lines_changed: int = 0


class VerificationCheck(BaseModel):
    """Single verification check item (§6.5)."""

    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    status: VisualStatus = VisualStatus.IDLE
    detail: str = ""


class VerificationViewModel(BaseModel):
    """View model representing the complete verification suite (§6.5)."""

    model_config = ConfigDict(frozen=True)

    overall_status: VisualStatus = VisualStatus.IDLE
    checks: list[VerificationCheck] = Field(default_factory=list)


class MyaViewModel(BaseModel):
    """View model for Mya visual character presence (§14, §15)."""

    model_config = ConfigDict(frozen=True)

    semantic_state: str = "IDLE"
    expression: str = "calm"
    pose: str = "neutral"
    activity: str = "idle"
    attention: str = "project"
    speech_mode: str = "concise"
    confidence_visual: str = "high"
    speech_bubble: str = ""
    avatar_mode: str = "dot"  # "dot" | "glyph" | "ascii" | "minimal"
    metadata: dict[str, Any] = Field(default_factory=dict)
