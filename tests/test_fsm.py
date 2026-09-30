"""Unit tests for the FSM and JobController transitions."""

from pathlib import Path

import pytest

from myagentos.core.errors import StateTransitionError
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store import EventStore
from myagentos.fsm import JobController, JobState


def test_job_controller_happy_path_planned_code(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    controller = JobController.create(job_id="job-fsm-1", event_store=store)

    assert controller.current_state == JobState.IDLE

    # 1. TASK_CREATED -> ROUTING
    state, _ = controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
    assert state == JobState.ROUTING

    # 2. ROUTE_SELECTED -> DATA_CLASSIFY
    state, _ = controller.transition(
        EventName.ROUTE_SELECTED,
        EventActor.ROUTER,
        payload={"intent": "PLANNED_CODE"},
    )
    assert state == JobState.DATA_CLASSIFY

    # 3. DATA_CLASSIFIED -> PLAN_CONTEXT
    state, _ = controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)
    assert state == JobState.PLAN_CONTEXT

    # 4. PLAN_CONTEXT_BUILT -> PLAN_SPEC
    state, _ = controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    assert state == JobState.PLAN_SPEC

    # 5. PLAN_GENERATED -> RISK_FINAL
    state, _ = controller.transition(
        EventName.PLAN_GENERATED,
        EventActor.PLANNER,
        payload={"plan_id": "p-1", "base_commit": "c-100"},
    )
    assert state == JobState.RISK_FINAL

    # 6. RISK_ASSESSED (HIGH) -> WAIT_PLAN_APPROVAL
    state, _ = controller.transition(
        EventName.RISK_ASSESSED,
        EventActor.POLICY_ENGINE,
        payload={"level": "HIGH"},
    )
    assert state == JobState.WAIT_PLAN_APPROVAL
    assert controller.risk_level == RiskLevel.HIGH

    # 7. APPROVAL_GRANTED -> WORKER_CONTEXT
    state, _ = controller.transition(EventName.APPROVAL_GRANTED, EventActor.USER)
    assert state == JobState.WORKER_CONTEXT

    # 8. WORKER_CONTEXT_BUILT -> WORKTREE_READY
    state, _ = controller.transition(EventName.WORKER_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    assert state == JobState.WORKTREE_READY

    # 9. WORKTREE_READY -> EXECUTE
    state, _ = controller.transition(
        EventName.WORKTREE_READY,
        EventActor.JOB_CONTROLLER,
        payload={"requires_test_authoring": False},
    )
    assert state == JobState.EXECUTE

    # 10. PATCH_CREATED -> POLICY_VALIDATION
    state, _ = controller.transition(EventName.PATCH_CREATED, EventActor.WORKER)
    assert state == JobState.POLICY_VALIDATION

    # 11. POLICY_CHECKED -> VERIFY
    state, _ = controller.transition(
        EventName.POLICY_CHECKED,
        EventActor.POLICY_ENGINE,
        payload={"risk_escalated": False},
    )
    assert state == JobState.VERIFY

    # 12. VERIFICATION_COMPLETED -> INDEPENDENT_REVIEW
    state, _ = controller.transition(
        EventName.VERIFICATION_COMPLETED, EventActor.VERIFICATION_GUARD
    )
    assert state == JobState.INDEPENDENT_REVIEW

    # 13. REVIEW_COMPLETED (HIGH risk) -> WAIT_DIFF_APPROVAL
    state, _ = controller.transition(
        EventName.REVIEW_COMPLETED,
        EventActor.INDEPENDENT_REVIEWER,
        payload={"risk_level": "HIGH"},
    )
    assert state == JobState.WAIT_DIFF_APPROVAL

    # 14. APPROVAL_GRANTED -> MERGE_CHECK
    state, _ = controller.transition(EventName.APPROVAL_GRANTED, EventActor.USER)
    assert state == JobState.MERGE_CHECK

    # 15. MERGE_COMPLETED -> MERGE
    state, _ = controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)
    assert state == JobState.MERGE

    # 16. MERGE_COMPLETED -> KNOWLEDGE_UPDATE
    state, _ = controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)
    assert state == JobState.KNOWLEDGE_UPDATE

    # 17. KNOWLEDGE_UPDATE_COMPLETED -> COMPLETE
    state, _ = controller.transition(EventName.KNOWLEDGE_UPDATE_COMPLETED, EventActor.CURATOR)
    assert state == JobState.COMPLETE
    assert state.is_terminal

    # Integrity verification
    store.assert_integrity("job-fsm-1")


def test_fast_route_low_risk_auto_approval(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    controller = JobController.create(job_id="job-fast-route", event_store=store)

    controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
    controller.transition(
        EventName.ROUTE_SELECTED,
        EventActor.ROUTER,
        payload={"intent": "DIRECT_WORKER_CODE"},
    )
    controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)
    controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PLAN_GENERATED, EventActor.PLANNER)

    # In LOW risk, RISK_ASSESSED directly auto-approves to WORKER_CONTEXT (§5.4 & §8.1)
    state, _ = controller.transition(
        EventName.RISK_ASSESSED,
        EventActor.POLICY_ENGINE,
        payload={"level": "LOW"},
    )
    assert state == JobState.WORKER_CONTEXT


def test_policy_violation_and_terminal_lock(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    controller = JobController.create(job_id="job-violation", event_store=store)

    controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.ROUTE_SELECTED, EventActor.ROUTER)
    controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)
    controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PLAN_GENERATED, EventActor.PLANNER)
    controller.transition(
        EventName.RISK_ASSESSED, EventActor.POLICY_ENGINE, payload={"level": "LOW"}
    )
    controller.transition(EventName.WORKER_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.WORKTREE_READY, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PATCH_CREATED, EventActor.WORKER)

    # Policy violation stops execution immediately
    state, _ = controller.transition(EventName.POLICY_VIOLATION, EventActor.POLICY_ENGINE)
    assert state == JobState.POLICY_VIOLATION
    assert state.is_terminal

    # Cannot transition out of terminal state
    with pytest.raises(StateTransitionError):
        controller.transition(EventName.RETRY_SCHEDULED, EventActor.JOB_CONTROLLER)


def test_post_merge_knowledge_update_non_blocking(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    controller = JobController.create(job_id="job-knowledge", event_store=store)

    # Set controller state directly for test
    controller.current_state = JobState.KNOWLEDGE_UPDATE

    # Even if JOB_FAILED arrives in KNOWLEDGE_UPDATE, merge stands -> COMPLETE (§22.2)
    state, _ = controller.transition(EventName.JOB_FAILED, EventActor.CURATOR)
    assert state == JobState.COMPLETE


def test_plan_obsolescence_rule(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    controller = JobController.create(job_id="job-stale", event_store=store)

    base_commit = "commit-A"
    current_commit = "commit-B"
    plan_scope = {"src/billing.py", "tests/test_billing.py"}
    protected_paths = ["tests/protected/**", "conftest.py"]

    # 1. Non-colliding changes: safe to rebase
    safe = controller.check_obsolescence(
        approved_base_commit=base_commit,
        current_commit=current_commit,
        changed_files_between_commits=["docs/readme.md", "src/auth.py"],
        plan_scope_files=plan_scope,
        protected_paths=protected_paths,
    )
    assert safe is True

    # 2. Scope collision: STALE_PLAN
    colliding = controller.check_obsolescence(
        approved_base_commit=base_commit,
        current_commit=current_commit,
        changed_files_between_commits=["src/billing.py"],
        plan_scope_files=plan_scope,
        protected_paths=protected_paths,
    )
    assert colliding is False

    # 3. Protected path collision: STALE_PLAN
    protected_collision = controller.check_obsolescence(
        approved_base_commit=base_commit,
        current_commit=current_commit,
        changed_files_between_commits=["conftest.py"],
        plan_scope_files=plan_scope,
        protected_paths=protected_paths,
    )
    assert protected_collision is False


def test_job_controller_continuation_flow(tmp_path: Path) -> None:
    """Verifies FSM transitions for the Project Continuation Audit flow (§6)."""
    store = EventStore(root_dir=tmp_path)
    controller = JobController.create(job_id="job-pca-1", event_store=store)

    assert controller.current_state == JobState.IDLE

    # 1. TASK_CREATED -> ROUTING
    state, _ = controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
    assert state == JobState.ROUTING

    # 2. ROUTE_SELECTED -> PROJECT_SNAPSHOT
    state, _ = controller.transition(
        EventName.ROUTE_SELECTED,
        EventActor.ROUTER,
        payload={"intent": "PROJECT_CONTINUATION"},
    )
    assert state == JobState.PROJECT_SNAPSHOT

    # 3. PROJECT_SNAPSHOT_CREATED -> STATIC_DISCOVERY
    state, _ = controller.transition(
        EventName.PROJECT_SNAPSHOT_CREATED,
        EventActor.JOB_CONTROLLER,
    )
    assert state == JobState.STATIC_DISCOVERY

    # 4. STATIC_DISCOVERY_COMPLETED (with dynamic diagnostics) -> DYNAMIC_DIAGNOSTICS
    state, _ = controller.transition(
        EventName.STATIC_DISCOVERY_COMPLETED,
        EventActor.JOB_CONTROLLER,
        payload={"dynamic": True},
    )
    assert state == JobState.DYNAMIC_DIAGNOSTICS

    # 5. DYNAMIC_DIAGNOSTICS_COMPLETED -> FINDING_CLASSIFICATION
    state, _ = controller.transition(
        EventName.DYNAMIC_DIAGNOSTICS_COMPLETED,
        EventActor.VERIFICATION_GUARD,
    )
    assert state == JobState.FINDING_CLASSIFICATION

    # 6. FINDING_CLASSIFIED -> CONTINUATION_SYNTHESIS
    state, _ = controller.transition(
        EventName.FINDING_CLASSIFIED,
        EventActor.JOB_CONTROLLER,
    )
    assert state == JobState.CONTINUATION_SYNTHESIS

    # 7. CONTINUATION_REPORT_CREATED -> CONTINUATION_REPORT_READY
    state, _ = controller.transition(
        EventName.CONTINUATION_REPORT_CREATED,
        EventActor.CONTINUITY_ANALYST,
    )
    assert state == JobState.CONTINUATION_REPORT_READY

    # 8. CONTINUATION_CONTEXT_VALIDATED -> COMPLETE
    state, _ = controller.transition(
        EventName.CONTINUATION_CONTEXT_VALIDATED,
        EventActor.JOB_CONTROLLER,
    )
    assert state == JobState.COMPLETE
    assert state.is_terminal is True
