"""Routing models and intents according to §6."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.risk import RiskLevel


class RoutingIntent(StrEnum):
    """Normative routing intents mapped to FSM branches (§6)."""

    DIRECT_WORKER_CODE = "DIRECT_WORKER_CODE"
    PLANNED_CODE = "PLANNED_CODE"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    DOC_LOOKUP = "DOC_LOOKUP"
    PROJECT_CONTINUATION = "PROJECT_CONTINUATION"
    ABSTAIN = "ABSTAIN"


class RoutingDecision(BaseModel):
    """The local deterministic classification output (§6)."""

    model_config = ConfigDict(frozen=True)

    intent: RoutingIntent
    preliminary_risk: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    matched_rule: str
    cleaned_prompt: str
