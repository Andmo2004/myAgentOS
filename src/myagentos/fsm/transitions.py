"""Deterministic state transitions and guard evaluations according to §8."""

from typing import Any

from myagentos.core.errors import StateTransitionError
from myagentos.core.models.event import EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.fsm.states import JobState


class TransitionTable:
    """Computes the target JobState deterministically from the current state, event, and payload."""

    @classmethod
    def get_next_state(
        cls,
        current_state: JobState,
        event_name: EventName,
        payload: dict[str, Any] | None = None,
    ) -> JobState:
        payload = payload or {}

        # Universal abort / cancel / timeout handlers
        if current_state.is_terminal:
            msg = f"Cannot leave terminal state {current_state.value} with {event_name.value}"
            raise StateTransitionError(msg)

        if event_name == EventName.JOB_CANCELLED:
            return JobState.CANCELLED

        if event_name == EventName.TIMEOUT:
            return JobState.TIMEOUT

        if event_name == EventName.BUDGET_PAUSED:
            return JobState.BUDGET_PAUSED

        if event_name == EventName.ESCALATED:
            return JobState.ESCALATED

        # State-specific transition logic
        if current_state == JobState.IDLE:
            if event_name == EventName.TASK_CREATED:
                return JobState.ROUTING

        elif current_state == JobState.ROUTING:
            if event_name == EventName.ROUTE_SELECTED:
                intent = payload.get("intent", "PLANNED_CODE")
                if intent == "DOC_LOOKUP":
                    return JobState.DOC_LOOKUP_RUN
                if intent == "DEEP_RESEARCH":
                    return JobState.RESEARCH_RUN
                if intent == "PROJECT_CONTINUATION":
                    return JobState.PROJECT_SNAPSHOT
                return JobState.DATA_CLASSIFY

        elif current_state in (JobState.DOC_LOOKUP_RUN, JobState.RESEARCH_RUN):
            if event_name in (EventName.JOB_COMPLETED, EventName.VERIFICATION_COMPLETED):
                return JobState.COMPLETE

        # Project Continuation Audit (PCA) transitions (§6.1, §6.2)
        elif current_state == JobState.PROJECT_SNAPSHOT:
            if event_name == EventName.PROJECT_SNAPSHOT_CREATED:
                return JobState.STATIC_DISCOVERY

        elif current_state == JobState.STATIC_DISCOVERY:
            if event_name == EventName.STATIC_DISCOVERY_COMPLETED:
                if payload.get("dynamic", False):
                    return JobState.DYNAMIC_DIAGNOSTICS
                return JobState.FINDING_CLASSIFICATION

        elif current_state == JobState.DYNAMIC_DIAGNOSTICS:
            if event_name == EventName.DYNAMIC_DIAGNOSTICS_COMPLETED:
                return JobState.FINDING_CLASSIFICATION

        elif current_state == JobState.FINDING_CLASSIFICATION:
            if event_name in (
                EventName.FINDING_CLASSIFIED,
                EventName.CONTINUATION_SYNTHESIS_STARTED,
            ):
                return JobState.CONTINUATION_SYNTHESIS

        elif current_state == JobState.CONTINUATION_SYNTHESIS:
            if event_name == EventName.CONTINUATION_REPORT_CREATED:
                return JobState.CONTINUATION_REPORT_READY

        elif current_state == JobState.CONTINUATION_REPORT_READY:
            if event_name in (
                EventName.JOB_COMPLETED,
                EventName.CONTINUATION_CONTEXT_VALIDATED,
            ):
                return JobState.COMPLETE

        elif current_state == JobState.DATA_CLASSIFY:
            if event_name == EventName.DATA_CLASSIFIED:
                return JobState.PLAN_CONTEXT
            if event_name == EventName.DATA_APPROVAL_REQUESTED:
                return JobState.WAIT_DATA_APPROVAL

        elif current_state == JobState.WAIT_DATA_APPROVAL:
            if event_name == EventName.DATA_APPROVAL_GRANTED:
                return JobState.PLAN_CONTEXT
            if event_name == EventName.DATA_APPROVAL_DENIED:
                return JobState.CANCELLED

        elif current_state == JobState.PLAN_CONTEXT:
            if event_name == EventName.PLAN_CONTEXT_BUILT:
                return JobState.PLAN_SPEC

        elif current_state == JobState.PLAN_SPEC:
            if event_name == EventName.PLAN_GENERATED:
                return JobState.RISK_FINAL

        elif current_state == JobState.RISK_FINAL:
            if event_name == EventName.RISK_ASSESSED:
                level_str = payload.get("level", "LOW")
                level = (
                    RiskLevel(level_str) if level_str in RiskLevel.__members__ else RiskLevel.LOW
                )
                if level == RiskLevel.LOW:
                    return JobState.WORKER_CONTEXT
                return JobState.WAIT_PLAN_APPROVAL
            if event_name == EventName.APPROVAL_REQUESTED:
                return JobState.WAIT_PLAN_APPROVAL

        elif current_state == JobState.WAIT_PLAN_APPROVAL:
            if event_name == EventName.APPROVAL_GRANTED:
                return JobState.WORKER_CONTEXT
            if event_name == EventName.APPROVAL_REJECTED:
                if payload.get("request_changes", False):
                    return JobState.PLAN_SPEC
                return JobState.CANCELLED

        elif current_state == JobState.WORKER_CONTEXT:
            if event_name == EventName.WORKER_CONTEXT_BUILT:
                return JobState.WORKTREE_READY

        elif current_state == JobState.WORKTREE_READY:
            if event_name == EventName.WORKTREE_READY:
                if payload.get("requires_test_authoring", False):
                    return JobState.TEST_AUTHORING
                return JobState.EXECUTE

        elif current_state == JobState.TEST_AUTHORING:
            if event_name == EventName.TEST_AUTHORED:
                return JobState.EXECUTE

        elif current_state == JobState.EXECUTE:
            if event_name == EventName.PATCH_CREATED:
                return JobState.POLICY_VALIDATION
            if event_name in (EventName.TEST_FAILED, EventName.FAILURE_CLASSIFIED):
                return JobState.FAILURE_CLASSIFY
            if event_name == EventName.JOB_FAILED:
                return JobState.CANCELLED

        elif current_state == JobState.POLICY_VALIDATION:
            if event_name == EventName.POLICY_CHECKED:
                if payload.get("risk_escalated", False):
                    return JobState.WAIT_PLAN_APPROVAL
                return JobState.VERIFY
            if event_name == EventName.POLICY_VIOLATION:
                return JobState.POLICY_VIOLATION

        elif current_state == JobState.VERIFY:
            if event_name == EventName.VERIFICATION_COMPLETED:
                return JobState.INDEPENDENT_REVIEW
            if event_name == EventName.TEST_FAILED:
                return JobState.FAILURE_CLASSIFY

        elif current_state == JobState.FAILURE_CLASSIFY:
            if event_name == EventName.FAILURE_CLASSIFIED:
                return JobState.FAILURE_CLASSIFY
            if event_name == EventName.RETRY_SCHEDULED:
                return JobState.EXECUTE
            if event_name == EventName.CONTEXT_EXPANDED:
                return JobState.WORKER_CONTEXT
            if event_name == EventName.ENV_REPAIR_STARTED:
                return JobState.EXECUTE
            if event_name == EventName.POLICY_VIOLATION:
                return JobState.POLICY_VIOLATION
            if event_name == EventName.MERGE_CONFLICT:
                return JobState.MERGE_CONFLICT
            if event_name == EventName.JOB_FAILED:
                return JobState.CANCELLED

        elif current_state == JobState.INDEPENDENT_REVIEW:
            if event_name == EventName.REVIEW_COMPLETED:
                risk_level_str = payload.get("risk_level", "LOW")
                risk_level = (
                    RiskLevel(risk_level_str)
                    if risk_level_str in RiskLevel.__members__
                    else RiskLevel.LOW
                )
                if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                    return JobState.WAIT_DIFF_APPROVAL
                return JobState.MERGE_CHECK
            if event_name == EventName.FAILURE_CLASSIFIED:
                return JobState.FAILURE_CLASSIFY

        elif current_state == JobState.WAIT_DIFF_APPROVAL:
            if event_name == EventName.APPROVAL_GRANTED:
                return JobState.MERGE_CHECK
            if event_name == EventName.APPROVAL_REJECTED:
                if payload.get("request_changes", False):
                    return JobState.EXECUTE
                return JobState.CANCELLED

        elif current_state == JobState.MERGE_CHECK:
            if event_name == EventName.MERGE_COMPLETED:
                return JobState.MERGE
            if event_name == EventName.MERGE_CONFLICT:
                return JobState.MERGE_CONFLICT
            if event_name == EventName.STALE_PLAN:
                return JobState.STALE_PLAN
            if event_name == EventName.BASE_REBASED:
                return JobState.VERIFY

        elif current_state == JobState.MERGE:
            if event_name == EventName.MERGE_COMPLETED:
                return JobState.KNOWLEDGE_UPDATE

        elif current_state == JobState.KNOWLEDGE_UPDATE:
            # Post-merge is strictly non-blocking (§8 & §22.2)
            if event_name in (
                EventName.KNOWLEDGE_UPDATE_COMPLETED,
                EventName.JOB_COMPLETED,
                EventName.JOB_FAILED,
            ):
                return JobState.COMPLETE
            if event_name in (
                EventName.NOTE_PROPOSED,
                EventName.NOTE_VALIDATED,
                EventName.KNOWLEDGE_UPDATE_STARTED,
            ):
                return JobState.KNOWLEDGE_UPDATE

        raise StateTransitionError(
            f"Invalid transition from state {current_state.value} with event {event_name.value}"
        )
