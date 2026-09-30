"""End-to-end Pipeline Orchestrator coordinating all subsystems.

Follows §8, §9, §10, and §13.
"""

import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from myagentos.context.compiler import ContextCompiler
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.models.failure import FailureCode, ObservedFailure
from myagentos.core.models.knowledge import CuratorInput, ProjectNote
from myagentos.core.models.patch import PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.review import DiffApproval, ReviewResult, ReviewSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.curator import CuratorAgent
from myagentos.failure.healing import HealingCoordinator
from myagentos.fsm.controller import JobController
from myagentos.fsm.states import JobState
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig, PipelineResult
from myagentos.planner.agent import PlannerAgent
from myagentos.planner.models import PlannerInput
from myagentos.policy.engine import PolicyEngine
from myagentos.reviewer import DiffApprovalManager, IndependentReviewer
from myagentos.router.models import RoutingIntent
from myagentos.router.rules import LocalRouter
from myagentos.sandbox.base import SandboxDriver
from myagentos.sandbox.mock import MockSandboxDriver
from myagentos.verification.guard import VerificationGuard, VerificationResult
from myagentos.worker.broker import ToolBroker
from myagentos.worker.loop import WorkerLoop
from myagentos.worktree.manager import WorktreeManager
from myagentos.worktree.patch_applier import apply_patch_set

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Executes the canonical, governance-bounded Agentic OS workflow (§8)."""

    def __init__(
        self,
        config: PipelineConfig,
        gateway: ModelGateway | None = None,
        event_store: EventStore | None = None,
        policy_engine: PolicyEngine | None = None,
        sandbox_driver: SandboxDriver | None = None,
        healing_coordinator: HealingCoordinator | None = None,
        independent_reviewer: IndependentReviewer | None = None,
        diff_approval_manager: DiffApprovalManager | None = None,
        curator_agent: CuratorAgent | None = None,
    ) -> None:
        self.config = config
        self.repo_root = config.repo_root.resolve()
        events_dir = self.repo_root / ".myagentos" / "events"
        self.event_store = event_store or EventStore(root_dir=events_dir)
        self.gateway = gateway or ModelGateway()
        self.policy_engine = policy_engine or PolicyEngine()
        self.sandbox_driver = sandbox_driver or MockSandboxDriver()
        self.healing_coordinator = healing_coordinator or HealingCoordinator()
        self.independent_reviewer = independent_reviewer or IndependentReviewer(
            gateway=self.gateway
        )
        self.diff_approval_manager = diff_approval_manager or DiffApprovalManager()
        self.curator_agent = curator_agent or CuratorAgent(
            repo_root=self.repo_root,
            gateway=self.gateway,
            model_id=self.config.curator_model_id or "mock",
        )

        self.router = LocalRouter()
        self.context_compiler = ContextCompiler(
            repo_root=self.repo_root, policy_engine=self.policy_engine
        )
        self.planner = PlannerAgent(
            gateway=self.gateway,
            model_id=config.model_id,
            event_store=self.event_store,
        )
        self.worktree_manager = WorktreeManager(repo_root=self.repo_root)
        self.verification_guard = VerificationGuard(sandbox_driver=self.sandbox_driver)

    def run(self, task_prompt: str, job_id: str | None = None) -> PipelineResult:
        """Executes the full pipeline through deterministic FSM transitions (§8.1)."""
        t0 = time.monotonic()
        job_id = job_id or f"job-{uuid.uuid4().hex[:8]}"
        controller = JobController.create(job_id=job_id, event_store=self.event_store)

        # 1. Task Creation
        controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)

        # 2. Local Routing
        decision = self.router.route(task_prompt)
        controller.transition(
            EventName.ROUTE_SELECTED,
            EventActor.ROUTER,
            payload={"intent": decision.intent.value},
        )

        # 3. Data Classification
        controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)

        # Determine base commit
        base_commit = self._get_base_commit()

        # 4. Plan Context & Planning
        controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)

        if decision.intent == RoutingIntent.DIRECT_WORKER_CODE:
            target_file = self._infer_target_file(task_prompt)
            plan = self.planner.generate_micro_plan(
                job_id=job_id,
                target_file=target_file,
                base_commit=base_commit,
                rationale="Fast route DIRECT_WORKER_CODE",
            )
        else:
            plan_ctx = self.context_compiler.compile_plan_context(
                job_id=job_id,
                prompt=task_prompt,
                base_commit=base_commit,
            )
            planner_input = PlannerInput(
                job_id=job_id,
                task_prompt=task_prompt,
                context=plan_ctx,
                base_commit=base_commit,
                version=1,
            )
            plan = self.planner.generate_plan(planner_input)

        controller.transition(
            EventName.PLAN_GENERATED,
            EventActor.PLANNER,
            payload={"plan_id": plan.plan_id, "base_commit": plan.base_commit},
        )

        # 5. Risk Assessment & Approval
        assessment = self.policy_engine.assess_risk(
            paths=list(plan.all_targeted_paths()),
            current_risk=plan.preliminary_risk,
        )
        state, _ = controller.transition(
            EventName.RISK_ASSESSED,
            EventActor.POLICY_ENGINE,
            payload={"level": assessment.level.value},
        )

        # Check approval if entering WAIT_PLAN_APPROVAL
        approval = None
        if state == JobState.WAIT_PLAN_APPROVAL:
            approved = self._request_plan_approval(plan, assessment.level)
            if not approved:
                controller.transition(EventName.APPROVAL_REJECTED, EventActor.USER)
                return self._build_result(
                    job_id=job_id,
                    success=False,
                    controller=controller,
                    intent=decision.intent.value,
                    plan=plan,
                    summary="Plan rejected by user or policy approval callback",
                    duration_seconds=time.monotonic() - t0,
                )
            approval = self.planner.create_approval(plan, risk_level=assessment.level)
            state, _ = controller.transition(EventName.APPROVAL_GRANTED, EventActor.USER)
        else:
            approval = self.planner.create_approval(
                plan, risk_level=RiskLevel.LOW, approved_by="policy"
            )

        # 6. Worker Context & Worktree
        token = self.policy_engine.issue_capability_token(
            job_id=job_id,
            worker_id="worker-1",
            plan=plan,
            risk_level=assessment.level,
        )
        controller.transition(EventName.WORKER_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)

        # Prepare isolated worktree
        worktree_path, is_ephemeral = self._prepare_worktree(job_id, base_commit)
        try:
            controller.transition(
                EventName.WORKTREE_READY,
                EventActor.JOB_CONTROLLER,
                payload={"requires_test_authoring": False},
            )

            # 7. Execute Worker Loop
            broker = ToolBroker(
                worktree_path=worktree_path,
                token=token,
                sandbox=self.sandbox_driver,
            )
            loop = WorkerLoop(
                gateway=self.gateway,
                broker=broker,
                job_id=job_id,
                token=token,
                model_id=self.config.model_id,
                event_store=self.event_store,
            )
            worker_result = loop.run(task_prompt)

            if not worker_result.success or not worker_result.patch_set:
                controller.transition(
                    EventName.JOB_FAILED,
                    EventActor.WORKER,
                    payload={"reason": worker_result.stop_reason},
                )
                return self._build_result(
                    job_id=job_id,
                    success=False,
                    controller=controller,
                    intent=decision.intent.value,
                    plan=plan,
                    summary=f"Worker loop stopped: {worker_result.stop_reason}",
                    duration_seconds=time.monotonic() - t0,
                )

            patch_set = worker_result.patch_set
            controller.transition(EventName.PATCH_CREATED, EventActor.WORKER)

            # 8. Policy Validation on PatchSet
            patch_ok, errs = self.policy_engine.validate_patch(patch_set, token)
            if not patch_ok:
                controller.transition(
                    EventName.POLICY_VIOLATION,
                    EventActor.POLICY_ENGINE,
                    payload={"errors": errs},
                )
                return self._build_result(
                    job_id=job_id,
                    success=False,
                    controller=controller,
                    intent=decision.intent.value,
                    plan=plan,
                    patch_set=patch_set,
                    summary=f"Policy violation: {'; '.join(errs)}",
                    duration_seconds=time.monotonic() - t0,
                )

            controller.transition(
                EventName.POLICY_CHECKED,
                EventActor.POLICY_ENGINE,
                payload={"risk_escalated": False},
            )

            # 9. Verification Guard & Healing Loop (§14)
            while True:
                verification_res = self.verification_guard.verify(
                    worktree_path=worktree_path,
                    base_commit=base_commit,
                )
                if verification_res.passed:
                    controller.transition(
                        EventName.VERIFICATION_COMPLETED,
                        EventActor.VERIFICATION_GUARD,
                    )
                    break

                # Verification failed -> transition to FAILURE_CLASSIFY
                controller.transition(
                    EventName.TEST_FAILED,
                    EventActor.VERIFICATION_GUARD,
                    payload={"diagnostics": verification_res.diagnostics},
                )

                observed = ObservedFailure(
                    stage="VERIFY",
                    exit_code=1,
                    raw_output=verification_res.diagnostics,
                    error_type=(
                        verification_res.failure_code.value
                        if verification_res.failure_code
                        else None
                    ),
                )
                healing_decision = self.healing_coordinator.evaluate(
                    job_id=job_id,
                    observed=observed,
                    diff_output=patch_set.to_unified_diff(),
                )

                # Record deterministic failure classification in event chain
                controller.transition(
                    EventName.FAILURE_CLASSIFIED,
                    EventActor.JOB_CONTROLLER,
                    payload={
                        "code": healing_decision.failure_record.code.value,
                        "action": healing_decision.action.value,
                        "attempt": healing_decision.retry_attempt,
                    },
                )

                # Emit corresponding action event
                controller.transition(
                    healing_decision.fsm_event,
                    EventActor.JOB_CONTROLLER,
                    payload={"instructions": healing_decision.diagnostic_instructions},
                )

                if not healing_decision.can_retry:
                    return self._build_result(
                        job_id=job_id,
                        success=False,
                        controller=controller,
                        intent=decision.intent.value,
                        plan=plan,
                        patch_set=patch_set,
                        verification=verification_res,
                        summary=(
                            f"Execution halted: {healing_decision.failure_record.code.value} "
                            f"({healing_decision.action.value}) — "
                            f"{healing_decision.failure_record.message}"
                        ),
                        duration_seconds=time.monotonic() - t0,
                    )

                # Retry: execute worker loop with healing diagnostic instructions
                retry_prompt = f"{task_prompt}\n\n{healing_decision.diagnostic_instructions}"
                worker_result = loop.run(retry_prompt)

                if not worker_result.success or not worker_result.patch_set:
                    controller.transition(
                        EventName.JOB_FAILED,
                        EventActor.WORKER,
                        payload={"reason": worker_result.stop_reason},
                    )
                    return self._build_result(
                        job_id=job_id,
                        success=False,
                        controller=controller,
                        intent=decision.intent.value,
                        plan=plan,
                        summary=f"Worker loop stopped on retry: {worker_result.stop_reason}",
                        duration_seconds=time.monotonic() - t0,
                    )

                patch_set = worker_result.patch_set
                controller.transition(EventName.PATCH_CREATED, EventActor.WORKER)

                # Policy validation on updated patch
                patch_ok, errs = self.policy_engine.validate_patch(patch_set, token)
                if not patch_ok:
                    controller.transition(
                        EventName.POLICY_VIOLATION,
                        EventActor.POLICY_ENGINE,
                        payload={"errors": errs},
                    )
                    return self._build_result(
                        job_id=job_id,
                        success=False,
                        controller=controller,
                        intent=decision.intent.value,
                        plan=plan,
                        patch_set=patch_set,
                        summary=f"Policy violation on retry: {'; '.join(errs)}",
                        duration_seconds=time.monotonic() - t0,
                    )

                controller.transition(
                    EventName.POLICY_CHECKED,
                    EventActor.POLICY_ENGINE,
                    payload={"risk_escalated": False},
                )

            # 10. Independent Review & Diff Approval (§15)
            review_spec = ReviewSpec(
                job_id=job_id,
                patch_set=patch_set,
                plan=plan,
                risk_level=assessment.level,
                worker_model_id=self.config.model_id,
                reviewer_model=self.config.reviewer_model_id,
            )
            review_res = self.independent_reviewer.review(review_spec)

            if not review_res.passed:
                controller.transition(
                    EventName.FAILURE_CLASSIFIED,
                    EventActor.INDEPENDENT_REVIEWER,
                    payload={
                        "code": FailureCode.REVIEW_REJECTED.value,
                        "findings": review_res.security_findings + review_res.quality_findings,
                    },
                )
                return self._build_result(
                    job_id=job_id,
                    success=False,
                    controller=controller,
                    intent=decision.intent.value,
                    plan=plan,
                    patch_set=patch_set,
                    verification=verification_res,
                    review=review_res,
                    summary=f"Independent review failed: {review_res.summary}",
                    duration_seconds=time.monotonic() - t0,
                )

            state, _ = controller.transition(
                EventName.REVIEW_COMPLETED,
                EventActor.INDEPENDENT_REVIEWER,
                payload={"risk_level": assessment.level.value},
            )

            diff_approval = None
            if state == JobState.WAIT_DIFF_APPROVAL:
                diff_approved = self._request_diff_approval(patch_set)
                if not diff_approved:
                    controller.transition(EventName.APPROVAL_REJECTED, EventActor.USER)
                    return self._build_result(
                        job_id=job_id,
                        success=False,
                        controller=controller,
                        intent=decision.intent.value,
                        plan=plan,
                        patch_set=patch_set,
                        verification=verification_res,
                        review=review_res,
                        summary="Diff approval rejected by user",
                        duration_seconds=time.monotonic() - t0,
                    )
                diff_approval = self.diff_approval_manager.create_approval(
                    job_id=job_id,
                    patch_set=patch_set,
                    approved=True,
                    approved_by="user",
                )
                controller.transition(EventName.APPROVAL_GRANTED, EventActor.USER)
            else:
                diff_approval = self.diff_approval_manager.create_approval(
                    job_id=job_id,
                    patch_set=patch_set,
                    approved=True,
                    approved_by="policy",
                )

            # 11. Merge Check & Merge
            # Apply sealed patch set to repository root
            apply_patch_set(self.repo_root, patch_set, verify_before_hash=False)

            controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)
            controller.transition(EventName.MERGE_COMPLETED, EventActor.MERGE_CONTROLLER)

            # 12. Knowledge Update & Complete (§22)
            knowledge_ctx = self.context_compiler.compile_knowledge_context(
                job_id=job_id,
                patch_set=patch_set,
                base_commit=base_commit,
            )

            curator_notes: list[ProjectNote] = []
            try:
                curator_input = CuratorInput(
                    job_id=job_id,
                    project_id=self.repo_root.name,
                    patch_set=patch_set,
                    plan=plan,
                    verification=verification_res,
                    base_commit=base_commit,
                    extracted_facts=knowledge_ctx,
                )
                curator_res = self.curator_agent.curate_knowledge(curator_input)
                curator_notes = curator_res.notes

                for note in curator_notes:
                    controller.transition(
                        EventName.NOTE_PROPOSED,
                        EventActor.CURATOR,
                        payload={"note_id": note.note_id, "anchors": note.anchors},
                    )
                    controller.transition(
                        EventName.NOTE_VALIDATED,
                        EventActor.CURATOR,
                        payload={"note_id": note.note_id, "status": note.status.value},
                    )
            except Exception as e:
                logger.warning("Knowledge curation encountered non-fatal error: %s", e)

            controller.transition(
                EventName.KNOWLEDGE_UPDATE_COMPLETED,
                EventActor.CURATOR,
                payload={"notes_count": len(curator_notes)},
            )

            return self._build_result(
                job_id=job_id,
                success=True,
                controller=controller,
                intent=decision.intent.value,
                plan=plan,
                approval=approval,
                patch_set=patch_set,
                verification=verification_res,
                review=review_res,
                diff_approval=diff_approval,
                notes=curator_notes,
                summary=(
                    f"Successfully applied {patch_set.total_files} file changes "
                    f"({patch_set.total_diff_lines} lines)"
                ),
                duration_seconds=time.monotonic() - t0,
            )

        finally:
            if is_ephemeral:
                self.worktree_manager.remove_worktree(job_id)

    def _get_base_commit(self) -> str:
        """Retrieves active commit hash or fallback."""
        if (self.repo_root / ".git").exists():
            try:
                res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                pass
        return "local-head"

    def _infer_target_file(self, prompt: str) -> str:
        """Heuristically extracts target path for micro-plans."""
        parts = prompt.split()
        for p in parts:
            clean = p.strip("`'\",")
            if clean.startswith("/") and "/" not in clean[1:]:
                # Slash command like /direct, /route, etc.
                continue
            if ("/" in clean and not clean.startswith("/")) or clean.endswith(
                (".py", ".md", ".txt", ".json", ".toml", ".ts", ".js")
            ):
                return clean
        return "src/main.py"

    def _request_plan_approval(self, plan: PlanSpec, risk: RiskLevel) -> bool:
        if self.config.auto_approve:
            return True
        if self.config.approval_callback:
            return self.config.approval_callback(plan.plan_id, plan)
        return True

    def _request_diff_approval(self, patch_set: PatchSet) -> bool:
        if self.config.auto_approve:
            return True
        if self.config.diff_approval_callback:
            return self.config.diff_approval_callback(patch_set.job_id, patch_set)
        return True

    def _prepare_worktree(self, job_id: str, base_commit: str) -> tuple[Path, bool]:
        """Creates ephemeral worktree if git available, else isolated temp directory."""
        has_git = (self.repo_root / ".git").exists()
        if self.config.use_worktree and has_git and base_commit != "local-head":
            try:
                wt = self.worktree_manager.create_worktree(job_id, base_commit)
                return wt, True
            except Exception:
                pass

        # Fallback to copy directory
        temp_dir = self.repo_root / ".myagentos" / "worktrees" / job_id
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.copytree(
            self.repo_root,
            temp_dir,
            ignore=shutil.ignore_patterns(".git", ".myagentos", "__pycache__", ".venv"),
        )
        return temp_dir, True

    def _build_result(
        self,
        job_id: str,
        success: bool,
        controller: JobController,
        intent: str,
        duration_seconds: float,
        plan: PlanSpec | None = None,
        approval: Any | None = None,
        patch_set: PatchSet | None = None,
        verification: VerificationResult | None = None,
        review: ReviewResult | None = None,
        diff_approval: DiffApproval | None = None,
        notes: list[ProjectNote] | None = None,
        summary: str = "",
    ) -> PipelineResult:
        chain_ok, _ = self.event_store.verify_integrity(job_id)
        events = self.event_store.load_events(job_id)

        return PipelineResult(
            job_id=job_id,
            success=success,
            final_state=controller.current_state,
            intent=intent,
            plan=plan,
            approval=approval,
            patch_set=patch_set,
            verification=verification,
            review=review,
            diff_approval=diff_approval,
            notes=notes or [],
            audit_events_count=len(events),
            hash_chain_intact=chain_ok,
            duration_seconds=duration_seconds,
            summary=summary,
        )
