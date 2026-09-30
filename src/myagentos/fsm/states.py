"""Finite state machine states enumeration according to §8.1 and §8.2."""

from enum import StrEnum


class JobState(StrEnum):
    """Exhaustive set of states in the Agentic OS FSM (§8)."""

    # Initial and routing states
    IDLE = "IDLE"
    ROUTING = "ROUTING"
    DOC_LOOKUP_RUN = "DOC_LOOKUP_RUN"
    RESEARCH_RUN = "RESEARCH_RUN"

    # Project Continuation Audit (PCA) states (§6.2)
    PROJECT_SNAPSHOT = "PROJECT_SNAPSHOT"
    STATIC_DISCOVERY = "STATIC_DISCOVERY"
    DYNAMIC_DIAGNOSTICS = "DYNAMIC_DIAGNOSTICS"
    FINDING_CLASSIFICATION = "FINDING_CLASSIFICATION"
    CONTINUATION_SYNTHESIS = "CONTINUATION_SYNTHESIS"
    CONTINUATION_REPORT_READY = "CONTINUATION_REPORT_READY"

    # Data governance
    DATA_CLASSIFY = "DATA_CLASSIFY"
    WAIT_DATA_APPROVAL = "WAIT_DATA_APPROVAL"

    # Planning and risk assessment
    PLAN_CONTEXT = "PLAN_CONTEXT"
    PLAN_SPEC = "PLAN_SPEC"
    RISK_FINAL = "RISK_FINAL"
    WAIT_PLAN_APPROVAL = "WAIT_PLAN_APPROVAL"

    # Execution preparation
    WORKER_CONTEXT = "WORKER_CONTEXT"
    WORKTREE_READY = "WORKTREE_READY"
    TEST_AUTHORING = "TEST_AUTHORING"

    # Execution and policy validation
    EXECUTE = "EXECUTE"
    POLICY_VALIDATION = "POLICY_VALIDATION"

    # Verification and review
    VERIFY = "VERIFY"
    FAILURE_CLASSIFY = "FAILURE_CLASSIFY"
    INDEPENDENT_REVIEW = "INDEPENDENT_REVIEW"
    WAIT_DIFF_APPROVAL = "WAIT_DIFF_APPROVAL"

    # Merge and post-merge memory
    MERGE_CHECK = "MERGE_CHECK"
    MERGE = "MERGE"
    KNOWLEDGE_UPDATE = "KNOWLEDGE_UPDATE"

    # Terminal states (§8.2)
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    STALE_PLAN = "STALE_PLAN"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    BUDGET_PAUSED = "BUDGET_PAUSED"
    ESCALATED = "ESCALATED"

    @property
    def is_terminal(self) -> bool:
        """Terminal states have no outward transitions (§8.2)."""
        return self in (
            JobState.COMPLETE,
            JobState.CANCELLED,
            JobState.TIMEOUT,
            JobState.STALE_PLAN,
            JobState.MERGE_CONFLICT,
            JobState.POLICY_VIOLATION,
            JobState.BUDGET_PAUSED,
            JobState.ESCALATED,
        )

    @property
    def is_waiting_human(self) -> bool:
        """States that require user intervention (§8.1)."""
        return self in (
            JobState.WAIT_DATA_APPROVAL,
            JobState.WAIT_PLAN_APPROVAL,
            JobState.WAIT_DIFF_APPROVAL,
        )
