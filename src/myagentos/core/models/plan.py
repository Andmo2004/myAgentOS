"""Plan specification, micro-plans, and versioned approvals according to §8.3, §8.4, and §5.4."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.data_policy import DataClassification
from myagentos.core.models.risk import RiskLevel


def _default_permissions() -> dict[str, list[str]]:
    return {"read": [], "write": [], "execute": []}


class PlanSpec(BaseModel):
    """Full plan specification produced by the Planner role (§8.3)."""

    model_config = ConfigDict(frozen=True)

    plan_id: str
    job_id: str
    version: int = 1
    base_commit: str = Field(..., description="Repository commit hash frozen at plan creation")
    files_to_modify: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    files_to_delete: list[str] = Field(default_factory=list)
    altered_interfaces: list[str] = Field(
        default_factory=list,
        description="Public signatures or exports being modified",
    )
    test_specs: list[str] = Field(
        default_factory=list,
        description="Acceptance criteria and specifications for the Test Author (§13.4)",
    )
    preliminary_risk: RiskLevel = Field(default=RiskLevel.LOW)
    risk_reasons: list[str] = Field(default_factory=list)
    permissions_requested: dict[str, list[str]] = Field(default_factory=_default_permissions)
    impact_summary: str = Field(default="")
    assumptions: list[str] = Field(default_factory=list)
    data_classification_max: DataClassification = Field(default=DataClassification.INTERNAL)

    def all_targeted_paths(self) -> set[str]:
        return set(self.files_to_modify + self.files_to_create + self.files_to_delete)

    def compute_scope_hash(self) -> str:
        """Calculates deterministic scope_hash over frozen paths and test specs (§8.4)."""
        data = {
            "base_commit": self.base_commit,
            "modify": sorted(self.files_to_modify),
            "create": sorted(self.files_to_create),
            "delete": sorted(self.files_to_delete),
            "altered_interfaces": sorted(self.altered_interfaces),
            "test_specs": sorted(self.test_specs),
            "permissions": {k: sorted(v) for k, v in sorted(self.permissions_requested.items())},
        }
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class MicroPlan(BaseModel):
    """Lightweight plan for the fast route DIRECT_WORKER_CODE (§5.4)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    base_commit: str
    target_file: str
    operation: str = "modify"
    test_command: str = ""
    rationale: str = ""

    def to_plan_spec(self, plan_id: str = "micro-1") -> PlanSpec:
        return PlanSpec(
            plan_id=plan_id,
            job_id=self.job_id,
            version=1,
            base_commit=self.base_commit,
            files_to_modify=[self.target_file] if self.operation == "modify" else [],
            files_to_create=[self.target_file] if self.operation == "create" else [],
            files_to_delete=[self.target_file] if self.operation == "delete" else [],
            altered_interfaces=[],
            test_specs=[f"Verify with command: {self.test_command}"] if self.test_command else [],
            preliminary_risk=RiskLevel.LOW,
            risk_reasons=["Direct mechanical single-file edit"],
            permissions_requested={
                "read": [self.target_file],
                "write": [self.target_file],
                "execute": [self.test_command] if self.test_command else [],
            },
            impact_summary="Single-file targeted fast path modification",
            assumptions=[],
            data_classification_max=DataClassification.INTERNAL,
        )


class PlanApproval(BaseModel):
    """Versioned human or policy authorization (§8.4)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["plan", "data", "diff"]
    job_id: str
    plan_id: str
    plan_version: int
    base_commit: str
    scope_hash: str
    risk_level: RiskLevel
    data_classification_max: DataClassification = DataClassification.INTERNAL
    policy_version: str = "2.1.0"
    approved_by: str = "user"
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
