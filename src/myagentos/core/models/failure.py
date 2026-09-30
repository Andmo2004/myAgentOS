"""Closed failure enumeration and escalation mapping according to §14."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FailureCode(StrEnum):
    """Closed enumeration of system failure classes (§14.1)."""

    SYNTAX_ERROR = "SYNTAX_ERROR"
    TEST_FAILURE = "TEST_FAILURE"
    CONTEXT_MISSING = "CONTEXT_MISSING"
    FLAKY_TEST = "FLAKY_TEST"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    UNKNOWN = "UNKNOWN"


class FailureAction(StrEnum):
    """Actions decided by the Failure Classifier (§14.1)."""

    RETRY = "RETRY"
    CONTEXT_EXPANSION = "CONTEXT_EXPANSION"
    ENV_REPAIR = "ENV_REPAIR"
    ESCALATED = "ESCALATED"
    STOP = "STOP"


class FailureRule(BaseModel):
    """Policy rule associated with a failure code (§14.1)."""

    model_config = ConfigDict(frozen=True)

    default_action: FailureAction
    max_occurrences_per_job: int


FAILURE_ACTION_MAP: dict[FailureCode, FailureRule] = {
    FailureCode.SYNTAX_ERROR: FailureRule(
        default_action=FailureAction.RETRY,
        max_occurrences_per_job=2,
    ),
    FailureCode.TEST_FAILURE: FailureRule(
        default_action=FailureAction.RETRY,
        max_occurrences_per_job=4,
    ),
    FailureCode.CONTEXT_MISSING: FailureRule(
        default_action=FailureAction.CONTEXT_EXPANSION,
        max_occurrences_per_job=2,
    ),
    FailureCode.FLAKY_TEST: FailureRule(
        default_action=FailureAction.ESCALATED,
        max_occurrences_per_job=1,
    ),
    FailureCode.ENVIRONMENT_ERROR: FailureRule(
        default_action=FailureAction.ENV_REPAIR,
        max_occurrences_per_job=2,
    ),
    FailureCode.DEPENDENCY_ERROR: FailureRule(
        default_action=FailureAction.ESCALATED,
        max_occurrences_per_job=1,
    ),
    FailureCode.POLICY_VIOLATION: FailureRule(
        default_action=FailureAction.STOP,
        max_occurrences_per_job=0,
    ),
    FailureCode.MERGE_CONFLICT: FailureRule(
        default_action=FailureAction.STOP,
        max_occurrences_per_job=0,
    ),
    FailureCode.REVIEW_REJECTED: FailureRule(
        default_action=FailureAction.RETRY,
        max_occurrences_per_job=3,
    ),
    FailureCode.BUDGET_EXHAUSTED: FailureRule(
        default_action=FailureAction.STOP,
        max_occurrences_per_job=0,
    ),
    FailureCode.UNKNOWN: FailureRule(
        default_action=FailureAction.ESCALATED,
        max_occurrences_per_job=0,
    ),
}


class FailureRecord(BaseModel):
    """Detailed record of an encountered failure during job execution."""

    model_config = ConfigDict(frozen=True)

    code: FailureCode
    action: FailureAction
    message: str
    attempt: int = 1
    max_allowed: int
    diagnostics: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
