"""Autonomous Planner Agent generating structured PlanSpec and approvals.

Follows §7, §8.3, and §8.4.
"""

import json
from typing import Any

from myagentos.context.models import CompiledContext
from myagentos.core.models.data_policy import DataClassification
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.models.plan import MicroPlan, PlanApproval, PlanSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway
from myagentos.planner.models import PlannerInput, PlanResponseSchema
from myagentos.planner.prompts import PLANNER_SYSTEM_PROMPT, format_planner_user_prompt


def _parse_plan_json(raw_text: str) -> dict[str, Any]:
    """Cleans markdown fences and parses JSON payload."""
    clean = raw_text.strip()
    if clean.startswith("```json"):
        clean = clean[len("```json") :].strip()
    if clean.startswith("```"):
        clean = clean[len("```") :].strip()
    if clean.endswith("```"):
        clean = clean[: -len("```")].strip()

    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {}


class PlannerAgent:
    """Produces minimal, verifiable PlanSpec objects from PLAN_CONTEXT (§7, §8.3)."""

    def __init__(
        self,
        gateway: ModelGateway,
        model_id: str = "mock-planner",
        event_store: EventStore | None = None,
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.event_store = event_store

    def generate_plan(self, input_data: PlannerInput) -> PlanSpec:
        """Executes Planner inference to generate an authoritative PlanSpec (§8.3)."""
        user_prompt = format_planner_user_prompt(input_data)
        messages = [
            LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        if self.event_store:
            self.event_store.append(
                job_id=input_data.job_id,
                actor=EventActor.PLANNER,
                state="PLAN_SPEC",
                event_name=EventName.MODEL_CALL_STARTED,
                payload={"model_id": self.model_id, "version": input_data.version},
            )

        resp = self.gateway.generate(
            messages=messages,
            model_id=self.model_id,
            temperature=0.0,
            response_schema=PlanResponseSchema,
        )

        if self.event_store:
            self.event_store.append(
                job_id=input_data.job_id,
                actor=EventActor.PLANNER,
                state="PLAN_SPEC",
                event_name=EventName.MODEL_CALL_COMPLETED,
                payload={
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                },
            )

        # Parse output
        raw_dict = _parse_plan_json(resp.content)
        parsed = PlanResponseSchema.model_validate(raw_dict) if raw_dict else PlanResponseSchema()

        # Normalize risk level
        risk_str = parsed.preliminary_risk.upper()
        risk_level = (
            RiskLevel(risk_str) if risk_str in RiskLevel.__members__ else RiskLevel.LOW
        )

        # Normalize data classification
        data_str = parsed.data_classification_max.lower()
        try:
            data_class = DataClassification(data_str)
        except ValueError:
            data_class = DataClassification.INTERNAL

        # Ensure permissions requested include all targeted files
        permissions = dict(parsed.permissions_requested)
        read_scope = set(permissions.get("read", []))
        write_scope = set(permissions.get("write", []))

        all_targets = set(parsed.files_to_modify + parsed.files_to_create + parsed.files_to_delete)
        read_scope.update(all_targets)
        write_scope.update(all_targets)

        permissions["read"] = sorted(read_scope)
        permissions["write"] = sorted(write_scope)
        permissions.setdefault("execute", ["pytest"])

        plan_id = f"plan-{input_data.job_id}-v{input_data.version}"
        plan = PlanSpec(
            plan_id=plan_id,
            job_id=input_data.job_id,
            version=input_data.version,
            base_commit=input_data.base_commit,
            files_to_modify=parsed.files_to_modify,
            files_to_create=parsed.files_to_create,
            files_to_delete=parsed.files_to_delete,
            altered_interfaces=parsed.altered_interfaces,
            test_specs=parsed.test_specs,
            preliminary_risk=risk_level,
            risk_reasons=parsed.risk_reasons,
            permissions_requested=permissions,
            impact_summary=parsed.impact_summary or parsed.rationale,
            assumptions=parsed.assumptions,
            data_classification_max=data_class,
        )

        if self.event_store:
            self.event_store.append(
                job_id=input_data.job_id,
                actor=EventActor.PLANNER,
                state="PLAN_SPEC",
                event_name=EventName.PLAN_GENERATED,
                payload={
                    "plan_id": plan.plan_id,
                    "version": plan.version,
                    "base_commit": plan.base_commit,
                    "scope_hash": plan.compute_scope_hash(),
                    "preliminary_risk": plan.preliminary_risk.value,
                    "targets_count": len(all_targets),
                },
            )

        return plan

    def generate_micro_plan(
        self,
        job_id: str,
        target_file: str,
        base_commit: str = "HEAD",
        operation: str = "modify",
        test_command: str = "pytest",
        rationale: str = "Fast route DIRECT_WORKER_CODE micro-plan",
    ) -> PlanSpec:
        """Generates a deterministic micro-plan without LLM cost (§5.4)."""
        micro = MicroPlan(
            job_id=job_id,
            base_commit=base_commit,
            target_file=target_file,
            operation=operation,
            test_command=test_command,
            rationale=rationale,
        )
        plan = micro.to_plan_spec(plan_id=f"plan-micro-{job_id}")

        if self.event_store:
            self.event_store.append(
                job_id=job_id,
                actor=EventActor.JOB_CONTROLLER,
                state="PLAN_SPEC",
                event_name=EventName.PLAN_GENERATED,
                payload={
                    "plan_id": plan.plan_id,
                    "version": plan.version,
                    "base_commit": plan.base_commit,
                    "scope_hash": plan.compute_scope_hash(),
                    "preliminary_risk": plan.preliminary_risk.value,
                    "is_micro_plan": True,
                },
            )

        return plan

    def replan_with_feedback(
        self,
        current_plan: PlanSpec,
        feedback: str,
        context: CompiledContext,
        task_prompt: str,
    ) -> PlanSpec:
        """Generates iteration v+1 following human REQUEST_CHANGES (§8.1, §8.4)."""
        next_input = PlannerInput(
            job_id=current_plan.job_id,
            task_prompt=task_prompt,
            context=context,
            base_commit=current_plan.base_commit,
            version=current_plan.version + 1,
            feedback=feedback,
        )
        return self.generate_plan(next_input)

    def create_approval(
        self,
        plan: PlanSpec,
        risk_level: RiskLevel,
        approved_by: str = "user",
    ) -> PlanApproval:
        """Stamps a cryptographic approval binding the plan scope (§8.4)."""
        approval = PlanApproval(
            kind="plan",
            job_id=plan.job_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            base_commit=plan.base_commit,
            scope_hash=plan.compute_scope_hash(),
            risk_level=risk_level,
            data_classification_max=plan.data_classification_max,
            approved_by=approved_by,
        )

        if self.event_store:
            self.event_store.append(
                job_id=plan.job_id,
                actor=EventActor.USER if approved_by == "user" else EventActor.POLICY_ENGINE,
                state="WAIT_PLAN_APPROVAL",
                event_name=EventName.APPROVAL_GRANTED,
                payload={
                    "plan_id": plan.plan_id,
                    "version": plan.version,
                    "scope_hash": approval.scope_hash,
                    "risk_level": risk_level.value,
                    "approved_by": approved_by,
                },
            )

        return approval
