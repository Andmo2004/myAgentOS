"""Boundary matrix tests for Plan Obsolescence and Automatic Rebase (§8.4, AUD-025, AUD-026)."""

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from myagentos.core.errors import StateTransitionError
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.fsm.controller import JobController
from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS


class ScriptedRebaseAdapter(ProviderAdapter):
    """Deterministic adapter returning fixed patch proposals."""

    def __init__(
        self,
        responses: list[str],
        on_generate: Callable[[], None] | None = None,
    ) -> None:
        self.responses = responses
        self.on_generate = on_generate
        self.index = 0

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type | None = None,
    ) -> LLMResponse:
        if self.on_generate:
            self.on_generate()
            self.on_generate = None
        if self.index < len(self.responses):
            resp = self.responses[self.index]
            self.index += 1
        else:
            resp = self.responses[-1]
        return LLMResponse(content=resp, model_id=model_id, input_tokens=40, output_tokens=60)


def _init_git_repo(repo_path: Path) -> str:
    """Helper to initialize git repository and create initial commit."""
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "agent@myagentos.local"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "AgentOS"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgSign", "false"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    readme = repo_path / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


# -------------------------------------------------------------------------
# AUD-026 Boundary Matrix Unit Tests
# -------------------------------------------------------------------------


def test_boundary_1_changed_file_outside_scope(tmp_path: Path) -> None:
    """AUD-026 Case 1: Changed file outside scope & dependencies -> Safe to rebase."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-aud026-1", event_store=store)

    plan_scope = {"src/billing/invoice.py"}
    dependency_closure = {"src/billing/tax.py", "tests/test_invoice.py"}

    # Changes occurred only in docs and unrelated services
    changed_files = ["docs/api.md", "src/auth/login.py", "assets/logo.png"]

    safe = controller.check_obsolescence(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=changed_files,
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert safe is True

    conflicts = controller.get_obsolescence_conflicts(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=changed_files,
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert conflicts == []


def test_boundary_2_changed_dependency_outside_direct_scope(tmp_path: Path) -> None:
    """AUD-026 Case 2: Changed dependency outside direct scope -> STALE_PLAN."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-aud026-2", event_store=store)

    plan_scope = {"src/billing/invoice.py"}
    # invoice.py imports tax.py, so tax.py is in dependency closure but NOT in direct write scope
    dependency_closure = {"src/billing/tax.py", "src/core/math.py"}

    changed_files = ["src/billing/tax.py"]

    safe = controller.check_obsolescence(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=changed_files,
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert safe is False

    conflicts = controller.get_obsolescence_conflicts(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=changed_files,
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert len(conflicts) == 1
    assert "src/billing/tax.py (dependency closure)" in conflicts[0]


def test_boundary_3_changed_protected_path(tmp_path: Path) -> None:
    """AUD-026 Case 3: Changed protected path -> STALE_PLAN."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-aud026-3", event_store=store)

    plan_scope = {"src/feature.py"}
    dependency_closure = {"src/feature_helpers.py"}

    # Case 3a: Protected tests directory
    safe_a = controller.check_obsolescence(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=["tests/protected/test_governance.py"],
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert safe_a is False

    # Case 3b: Root test configuration (conftest.py)
    safe_b = controller.check_obsolescence(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=["conftest.py"],
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert safe_b is False

    conflicts = controller.get_obsolescence_conflicts(
        approved_base_commit="commit-v1",
        current_commit="commit-v2",
        changed_files_between_commits=["conftest.py"],
        plan_scope_files=plan_scope,
        protected_paths=DEFAULT_PROTECTED_PATHS,
        dependency_closure=dependency_closure,
    )
    assert len(conflicts) == 1
    assert "conftest.py (protected path)" in conflicts[0]


def test_boundary_4_changed_config_indirect_impact(tmp_path: Path) -> None:
    """AUD-026 Case 4: Changed config with indirect impact -> STALE_PLAN."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-aud026-4", event_store=store)

    plan_scope = {"src/service.py"}
    dependency_closure = {"src/service_client.py"}

    manifest_candidates = [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "Cargo.toml",
        "poetry.lock",
        "uv.lock",
    ]

    for manifest in manifest_candidates:
        safe = controller.check_obsolescence(
            approved_base_commit="commit-v1",
            current_commit="commit-v2",
            changed_files_between_commits=[manifest],
            plan_scope_files=plan_scope,
            protected_paths=DEFAULT_PROTECTED_PATHS,
            dependency_closure=dependency_closure,
        )
        assert safe is False, f"Manifest {manifest} should collide and trigger STALE_PLAN"

        conflicts = controller.get_obsolescence_conflicts(
            approved_base_commit="commit-v1",
            current_commit="commit-v2",
            changed_files_between_commits=[manifest],
            plan_scope_files=plan_scope,
            protected_paths=DEFAULT_PROTECTED_PATHS,
            dependency_closure=dependency_closure,
        )
        assert len(conflicts) == 1
        assert f"{manifest} (config/manifest)" in conflicts[0]


def test_boundary_same_commit_no_change(tmp_path: Path) -> None:
    """Obsolescence rule is a no-op when base commit equals current commit."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-aud026-same", event_store=store)

    safe = controller.check_obsolescence(
        approved_base_commit="commit-v1",
        current_commit="commit-v1",
        changed_files_between_commits=[],
        plan_scope_files={"src/app.py"},
        protected_paths=DEFAULT_PROTECTED_PATHS,
    )
    assert safe is True


# -------------------------------------------------------------------------
# FSM State & Transition Unit Tests
# -------------------------------------------------------------------------


def test_fsm_stale_plan_is_terminal(tmp_path: Path) -> None:
    """Verifies MERGE_CHECK -> STALE_PLAN transition and terminality (§8.2)."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-fsm-stale", event_store=store)

    # Fast-forward FSM to MERGE_CHECK
    controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.ROUTE_SELECTED, EventActor.ROUTER, {"intent": "DIRECT"})
    controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)
    controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PLAN_GENERATED, EventActor.PLANNER)
    controller.transition(EventName.RISK_ASSESSED, EventActor.POLICY_ENGINE, {"level": "LOW"})
    controller.transition(EventName.WORKER_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.WORKTREE_READY, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PATCH_CREATED, EventActor.WORKER)
    controller.transition(EventName.POLICY_CHECKED, EventActor.POLICY_ENGINE)
    controller.transition(EventName.VERIFICATION_COMPLETED, EventActor.VERIFICATION_GUARD)
    controller.transition(
        EventName.REVIEW_COMPLETED, EventActor.INDEPENDENT_REVIEWER, {"risk_level": "LOW"}
    )
    assert controller.current_state.value == JobState.MERGE_CHECK.value

    # Trigger STALE_PLAN
    stale_state, _ = controller.transition(
        EventName.STALE_PLAN,
        EventActor.JOB_CONTROLLER,
        payload={"reason": "Obsolescence collision detected"},
    )
    assert stale_state == JobState.STALE_PLAN
    assert controller.current_state.value == JobState.STALE_PLAN.value
    assert controller.current_state.is_terminal is True

    # Terminal states reject any further transitions
    with pytest.raises(StateTransitionError):
        controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)


def test_fsm_base_rebased_and_reverification_flow(tmp_path: Path) -> None:
    """Verifies MERGE_CHECK -> BASE_REBASED -> VERIFY -> review -> MERGE flow (§8.4)."""
    store = EventStore(tmp_path)
    controller = JobController.create(job_id="job-fsm-rebase", event_store=store)

    # Fast-forward to MERGE_CHECK
    controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.ROUTE_SELECTED, EventActor.ROUTER, {"intent": "DIRECT"})
    controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)
    controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PLAN_GENERATED, EventActor.PLANNER)
    controller.transition(EventName.RISK_ASSESSED, EventActor.POLICY_ENGINE, {"level": "LOW"})
    controller.transition(EventName.WORKER_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.WORKTREE_READY, EventActor.JOB_CONTROLLER)
    controller.transition(EventName.PATCH_CREATED, EventActor.WORKER)
    controller.transition(EventName.POLICY_CHECKED, EventActor.POLICY_ENGINE)
    controller.transition(EventName.VERIFICATION_COMPLETED, EventActor.VERIFICATION_GUARD)
    controller.transition(
        EventName.REVIEW_COMPLETED, EventActor.INDEPENDENT_REVIEWER, {"risk_level": "LOW"}
    )
    assert controller.current_state.value == JobState.MERGE_CHECK.value

    # 1. Automatic rebase succeeds: BASE_REBASED transitions to VERIFY
    state1, _ = controller.transition(
        EventName.BASE_REBASED,
        EventActor.JOB_CONTROLLER,
        payload={"new_base": "commit-head"},
    )
    assert state1 == JobState.VERIFY

    # 2. Re-verification succeeds: transitions to INDEPENDENT_REVIEW
    state2, _ = controller.transition(
        EventName.VERIFICATION_COMPLETED,
        EventActor.VERIFICATION_GUARD,
    )
    assert state2 == JobState.INDEPENDENT_REVIEW

    # 3. Review completes (LOW risk): transitions back to MERGE_CHECK
    state3, _ = controller.transition(
        EventName.REVIEW_COMPLETED,
        EventActor.INDEPENDENT_REVIEWER,
        payload={"risk_level": "LOW"},
    )
    assert state3 == JobState.MERGE_CHECK

    # 4. Merge transitions: MERGE_CHECK -> MERGE -> KNOWLEDGE_UPDATE -> COMPLETE
    state4, _ = controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)
    assert state4 == JobState.MERGE

    state5, _ = controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)
    assert state5 == JobState.KNOWLEDGE_UPDATE

    state6, _ = controller.transition(
        EventName.KNOWLEDGE_UPDATE_COMPLETED,
        EventActor.CURATOR,
    )
    assert state6 == JobState.COMPLETE


# -------------------------------------------------------------------------
# End-to-End Pipeline Obsolescence & Rebase Integration Tests
# -------------------------------------------------------------------------


def test_pipeline_e2e_rebase_matrix_safe_rebase(tmp_path: Path) -> None:
    """E2E Test: Safe concurrent commit outside scope triggers automatic rebase & merge."""
    _init_git_repo(tmp_path)

    # Target source file
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    calc_file = src_dir / "calc.py"
    calc_file.write_text("def mul(a, b): return a + b\n", encoding="utf-8")

    # Commit calc.py so it is part of repo
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "add calc.py"], cwd=str(tmp_path), check=True)

    # Worker response proposing to fix calc.py
    worker_resp = json.dumps(
        {
            "thought": "Fix multiplication",
            "propose_patch": {
                "description": "Fix mul operator",
                "files": [
                    {
                        "path": "src/calc.py",
                        "operation": "MODIFY",
                        "content": "def mul(a, b): return a * b\n",
                    }
                ],
            },
        }
    )

    def concurrent_commit_outside_scope() -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# Test Repo (Updated by teammate)\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
        subprocess.run(["git", "commit", "-m", "update readme docs"], cwd=str(tmp_path), check=True)

    adapter = ScriptedRebaseAdapter([worker_resp], on_generate=concurrent_commit_outside_scope)
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=False,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)

    result = orchestrator.run("/direct fix mul in src/calc.py")

    assert result.success is True
    assert result.final_state == JobState.COMPLETE
    # Verify calc.py was updated
    assert calc_file.read_text() == "def mul(a, b): return a * b\n"
    # Verify event chain logged BASE_REBASED
    events = [e.event_name for e in orchestrator.event_store.load_events(result.job_id)]
    assert EventName.BASE_REBASED in events
    assert EventName.MERGE_COMPLETED in events


def test_pipeline_e2e_rebase_matrix_stale_dependency(tmp_path: Path) -> None:
    """E2E Test: Concurrent commit modifying dependency closure aborts with STALE_PLAN."""
    _init_git_repo(tmp_path)

    # Setup modular structure: main.py imports util.py
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    util_file = src_dir / "util.py"
    util_file.write_text("def helper(): return 1\n", encoding="utf-8")

    main_file = src_dir / "main.py"
    main_file.write_text(
        "from src.util import helper\ndef run(): return helper()\n", encoding="utf-8"
    )

    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial modules"], cwd=str(tmp_path), check=True)

    # Worker response modifying only main.py
    worker_resp = json.dumps(
        {
            "thought": "Update run in main.py",
            "propose_patch": {
                "description": "Update run function",
                "files": [
                    {
                        "path": "src/main.py",
                        "operation": "MODIFY",
                        "content": "from src.util import helper\ndef run(): return helper() + 10\n",
                    }
                ],
            },
        }
    )

    def concurrent_commit_modifying_dependency() -> None:
        util_file.write_text("def helper(): return 999\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
        subprocess.run(
            ["git", "commit", "-m", "modify helper signature"],
            cwd=str(tmp_path),
            check=True,
        )

    adapter = ScriptedRebaseAdapter(
        [worker_resp], on_generate=concurrent_commit_modifying_dependency
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=False,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)

    result = orchestrator.run("/direct update run in src/main.py")

    # Should detect collision with dependency closure and halt safely
    assert result.success is False
    assert result.final_state == JobState.STALE_PLAN
    assert "Plan is stale" in result.summary
    assert "src/util.py (dependency closure)" in result.summary

    # Ensure main.py was NOT merged / corrupted
    assert "return helper() + 10" not in main_file.read_text()
