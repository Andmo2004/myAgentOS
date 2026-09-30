"""Unit tests for PlannerAgent, PlanSpec generation, and versioned approvals (§7, §8.3, §8.4)."""

import json
from pathlib import Path

from myagentos.context.compiler import ContextCompiler
from myagentos.core.models.event import EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.planner.agent import PlannerAgent
from myagentos.planner.models import PlannerInput


class ScriptedAdapter(ProviderAdapter):
    """Sequential scripted responses for testing Planner inference."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.index = 0
        self.last_messages: list[LLMMessage] = []

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type | None = None,
    ) -> LLMResponse:
        self.last_messages = messages
        if self.index < len(self.responses):
            resp = self.responses[self.index]
            self.index += 1
        else:
            resp = self.responses[-1]
        return LLMResponse(content=resp, model_id=model_id, input_tokens=25, output_tokens=40)


def test_planner_generate_plan_structured_output(tmp_path: Path) -> None:
    # 1. Prepare dummy repo & context
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_file = src_dir / "payment.py"
    target_file.write_text("class PaymentProcessor:\n    def charge(self, amount: int): pass\n")

    compiler = ContextCompiler(repo_root=tmp_path)
    plan_ctx = compiler.compile_plan_context(
        job_id="job-plan-1",
        prompt="Add refund support to payment processor",
        seed_paths=["src/payment.py"],
        base_commit="c-plan-100",
    )

    # 2. Scripted LLM JSON output
    llm_payload = {
        "files_to_modify": ["src/payment.py"],
        "files_to_create": ["src/refund.py"],
        "files_to_delete": [],
        "altered_interfaces": ["PaymentProcessor.refund(charge_id: str, amount: int) -> bool"],
        "test_specs": ["test_refund_success_returns_true", "test_refund_negative_raises_error"],
        "preliminary_risk": "MEDIUM",
        "risk_reasons": ["Touches financial payment handling logic"],
        "permissions_requested": {
            "read": ["src/payment.py"],
            "write": ["src/payment.py", "src/refund.py"],
            "execute": ["pytest tests/test_payment.py"],
        },
        "impact_summary": "Extends payment module with refund capabilities",
        "assumptions": ["Payment gateway supports partial refunds"],
        "data_classification_max": "internal",
        "rationale": "Separates refund data models into src/refund.py",
    }
    adapter = ScriptedAdapter([json.dumps(llm_payload)])
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    store = EventStore(root_dir=tmp_path / ".events")
    agent = PlannerAgent(gateway=gateway, model_id="mock", event_store=store)

    planner_input = PlannerInput(
        job_id="job-plan-1",
        task_prompt="Add refund support to payment processor",
        context=plan_ctx,
        base_commit="c-plan-100",
        version=1,
    )

    plan = agent.generate_plan(planner_input)

    # Verifications (§8.3)
    assert plan.plan_id == "plan-job-plan-1-v1"
    assert plan.version == 1
    assert plan.base_commit == "c-plan-100"
    assert plan.files_to_modify == ["src/payment.py"]
    assert plan.files_to_create == ["src/refund.py"]
    assert len(plan.altered_interfaces) == 1
    assert "PaymentProcessor.refund" in plan.altered_interfaces[0]
    assert plan.preliminary_risk == RiskLevel.MEDIUM
    assert "src/refund.py" in plan.permissions_requested["write"]
    assert len(plan.compute_scope_hash()) == 64

    # Verify audit events in event store
    events = store.load_events("job-plan-1")
    event_names = [e.event_name for e in events]
    assert EventName.MODEL_CALL_STARTED in event_names
    assert EventName.MODEL_CALL_COMPLETED in event_names
    assert EventName.PLAN_GENERATED in event_names


def test_planner_replan_with_feedback(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_file = src_dir / "calc.py"
    target_file.write_text("def add(a, b): return a + b\n")

    compiler = ContextCompiler(repo_root=tmp_path)
    plan_ctx = compiler.compile_plan_context(
        job_id="job-replan-1",
        prompt="Add subtract function",
        seed_paths=["src/calc.py"],
        base_commit="c-replan-100",
    )

    resp_v1 = {
        "files_to_modify": ["src/calc.py"],
        "files_to_create": ["src/math_extra.py"],
        "altered_interfaces": [],
        "test_specs": ["test_subtract"],
        "preliminary_risk": "HIGH",
        "rationale": "Create new module",
    }
    resp_v2 = {
        "files_to_modify": ["src/calc.py"],
        "files_to_create": [],
        "altered_interfaces": ["def subtract(a: int, b: int) -> int"],
        "test_specs": ["test_subtract"],
        "preliminary_risk": "LOW",
        "rationale": "Keep everything in src/calc.py as requested",
    }

    adapter = ScriptedAdapter([json.dumps(resp_v1), json.dumps(resp_v2)])
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    agent = PlannerAgent(gateway=gateway, model_id="mock")

    # Step 1: Initial plan v1
    input_v1 = PlannerInput(
        job_id="job-replan-1",
        task_prompt="Add subtract function",
        context=plan_ctx,
        base_commit="c-replan-100",
        version=1,
    )
    plan_v1 = agent.generate_plan(input_v1)
    assert plan_v1.version == 1
    assert "src/math_extra.py" in plan_v1.files_to_create

    # Step 2: User requests changes (§8.1)
    feedback = "Do not create src/math_extra.py; add subtract directly to src/calc.py"
    plan_v2 = agent.replan_with_feedback(
        current_plan=plan_v1,
        feedback=feedback,
        context=plan_ctx,
        task_prompt="Add subtract function",
    )

    assert plan_v2.version == 2
    assert plan_v2.plan_id == "plan-job-replan-1-v2"
    assert plan_v2.files_to_create == []
    assert plan_v2.preliminary_risk == RiskLevel.LOW
    assert any("Feedback (Iteration v2)" in m.content for m in adapter.last_messages)


def test_planner_generate_micro_plan_fast_path(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path / ".events")
    gateway = ModelGateway()
    agent = PlannerAgent(gateway=gateway, model_id="mock", event_store=store)

    micro_plan = agent.generate_micro_plan(
        job_id="job-micro-1",
        target_file="src/utils.py",
        base_commit="c-micro-base",
        operation="modify",
        test_command="pytest tests/test_utils.py",
        rationale="Typo fix in docstring",
    )

    assert micro_plan.plan_id == "plan-micro-job-micro-1"
    assert micro_plan.files_to_modify == ["src/utils.py"]
    assert micro_plan.preliminary_risk == RiskLevel.LOW
    assert "pytest tests/test_utils.py" in micro_plan.permissions_requested["execute"]

    events = store.load_events("job-micro-1")
    assert any(e.event_name == EventName.PLAN_GENERATED for e in events)


def test_planner_create_approval(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path / ".events")
    agent = PlannerAgent(gateway=ModelGateway(), model_id="mock", event_store=store)

    plan = agent.generate_micro_plan(
        job_id="job-approve-1",
        target_file="src/service.py",
        base_commit="c-commit-5",
    )

    approval = agent.create_approval(
        plan=plan,
        risk_level=RiskLevel.LOW,
        approved_by="alice",
    )

    assert approval.kind == "plan"
    assert approval.plan_id == plan.plan_id
    assert approval.plan_version == plan.version
    assert approval.base_commit == plan.base_commit
    assert approval.scope_hash == plan.compute_scope_hash()
    assert approval.approved_by == "alice"

    events = store.load_events("job-approve-1")
    assert any(e.event_name == EventName.APPROVAL_GRANTED for e in events)
