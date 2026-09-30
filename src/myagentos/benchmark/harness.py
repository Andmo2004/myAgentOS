"""Benchmark Harness for empirical measurement of routing, risk, and verification (§26, §28)."""

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.fsm.controller import JobController
from myagentos.fsm.states import JobState
from myagentos.policy.engine import PolicyEngine
from myagentos.router.models import RoutingIntent
from myagentos.router.rules import LocalRouter


@dataclass(frozen=True)
class BenchmarkTask:
    """Benchmark task specification for reproducible validation (§26)."""

    task_id: str
    prompt: str
    target_files: list[str]
    expected_intent: RoutingIntent
    expected_risk: RiskLevel


@dataclass
class BenchmarkMetric:
    """Measured telemetry metrics per task (§26.2)."""

    task_id: str
    intent_match: bool
    false_direct: bool
    risk_monotonically_preserved: bool
    final_state: JobState
    duration_seconds: float
    hash_chain_intact: bool


class BenchmarkHarness:
    """Evaluates myagentos architecture against empirical criteria before MVP release (§26, §28)."""

    def __init__(self, store_dir: Path) -> None:
        self.store = EventStore(root_dir=store_dir)
        self.router = LocalRouter()
        self.policy_engine = PolicyEngine()

    def run_task(self, task: BenchmarkTask) -> BenchmarkMetric:
        start_time = time.monotonic()
        job_id = f"bench-{task.task_id}-{uuid.uuid4().hex[:6]}"
        controller = JobController.create(job_id=job_id, event_store=self.store)

        # 1. Routing
        controller.transition(EventName.TASK_CREATED, EventActor.JOB_CONTROLLER)
        decision = self.router.route(task.prompt)

        intent_match = decision.intent == task.expected_intent
        # False-direct detection: if expected risk is HIGH+ but routed to DIRECT_WORKER_CODE
        false_direct = (
            decision.intent == RoutingIntent.DIRECT_WORKER_CODE
            and task.expected_risk >= RiskLevel.MEDIUM
        )

        controller.transition(
            EventName.ROUTE_SELECTED,
            EventActor.ROUTER,
            payload={"intent": decision.intent.value},
        )

        # 2. Data classification
        controller.transition(EventName.DATA_CLASSIFIED, EventActor.POLICY_ENGINE)

        # 3. Planning & Risk Assessment
        controller.transition(EventName.PLAN_CONTEXT_BUILT, EventActor.JOB_CONTROLLER)

        plan = PlanSpec(
            plan_id=f"plan-{job_id}",
            job_id=job_id,
            base_commit="bench-base-commit",
            files_to_modify=task.target_files,
            preliminary_risk=decision.preliminary_risk,
            permissions_requested={"read": task.target_files, "write": task.target_files},
        )
        controller.transition(
            EventName.PLAN_GENERATED,
            EventActor.PLANNER,
            payload={"plan_id": plan.plan_id, "base_commit": plan.base_commit},
        )

        # Policy risk assessment
        assessment = self.policy_engine.assess_risk(
            paths=task.target_files,
            current_risk=decision.preliminary_risk,
        )
        risk_preserved = assessment.level >= decision.preliminary_risk

        controller.transition(
            EventName.RISK_ASSESSED,
            EventActor.POLICY_ENGINE,
            payload={"level": assessment.level.value},
        )

        # Verify hash chain
        chain_ok, _ = self.store.verify_integrity(job_id)
        duration = time.monotonic() - start_time

        return BenchmarkMetric(
            task_id=task.task_id,
            intent_match=intent_match,
            false_direct=false_direct,
            risk_monotonically_preserved=risk_preserved,
            final_state=controller.current_state,
            duration_seconds=duration,
            hash_chain_intact=chain_ok,
        )
