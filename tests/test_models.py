"""Unit tests for myagentos core domain models."""

import pytest

from myagentos.core.errors import RiskMonotonicityViolation
from myagentos.core.models import (
    GENESIS_HASH,
    CapabilityToken,
    DataClassification,
    Event,
    EventActor,
    EventName,
    FilePatch,
    MicroPlan,
    NetworkScope,
    PatchOperation,
    PatchSet,
    PlanSpec,
    RiskLevel,
    TokenLimits,
    TrustTag,
)


def test_risk_level_ordering_and_monotonicity() -> None:
    assert RiskLevel.LOW < RiskLevel.MEDIUM < RiskLevel.HIGH < RiskLevel.CRITICAL
    assert RiskLevel.CRITICAL >= RiskLevel.HIGH

    # Monotonic escalation passes when level goes up or stays same
    current = RiskLevel.MEDIUM
    assert current.escalate_to(RiskLevel.HIGH) == RiskLevel.HIGH
    assert current.escalate_to(RiskLevel.MEDIUM) == RiskLevel.MEDIUM

    # Monotonic escalation raises violation when trying to de-escalate
    with pytest.raises(RiskMonotonicityViolation):
        current.escalate_to(RiskLevel.LOW)


def test_data_classification_and_trust_tag() -> None:
    assert (
        DataClassification.PUBLIC
        < DataClassification.INTERNAL
        < DataClassification.CONFIDENTIAL
        < DataClassification.SECRET
    )
    combined = DataClassification.INTERNAL.combine_with(DataClassification.CONFIDENTIAL)
    assert combined == DataClassification.CONFIDENTIAL

    # Untrusted inheritance
    assert TrustTag.TRUSTED.combine_with(TrustTag.TRUSTED) == TrustTag.TRUSTED
    assert TrustTag.TRUSTED.combine_with(TrustTag.UNTRUSTED) == TrustTag.UNTRUSTED
    assert TrustTag.UNTRUSTED.combine_with(TrustTag.TRUSTED) == TrustTag.UNTRUSTED


def test_capability_token_permissions_and_intersection() -> None:
    token1 = CapabilityToken(
        job_id="job-1",
        worker_id="w-1",
        risk_level=RiskLevel.MEDIUM,
        read_scope=["src/**", "tests/**"],
        write_scope=["src/payments/*.py"],
        execute_scope=["pytest tests/unit", "ruff check"],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(max_files=3, max_diff_lines=150, max_steps=10),
        base_commit="commit-aaa",
    )

    assert token1.is_read_allowed("src/payments/service.py")
    assert token1.is_read_allowed("tests/unit/test_service.py")
    assert not token1.is_read_allowed("secrets/config.json")

    assert token1.is_write_allowed("src/payments/service.py")
    assert not token1.is_write_allowed("src/core/main.py")

    assert token1.is_execute_allowed("pytest tests/unit")
    assert token1.is_execute_allowed("pytest tests/unit -v")
    assert not token1.is_execute_allowed("rm -rf /")

    # Intersect with a more restrictive token
    token2 = CapabilityToken(
        job_id="job-1",
        worker_id="w-2",
        risk_level=RiskLevel.HIGH,
        read_scope=["src/payments/**"],
        write_scope=["src/payments/service.py"],
        execute_scope=["pytest tests/unit"],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(max_files=1, max_diff_lines=50, max_steps=5),
        base_commit="commit-aaa",
    )

    intersected = token1.intersect_with(token2)
    assert intersected.risk_level == RiskLevel.HIGH
    assert intersected.write_scope == ["src/payments/service.py"]
    assert intersected.execute_scope == ["pytest tests/unit"]
    assert intersected.limits.max_files == 1
    assert intersected.limits.max_diff_lines == 50


def test_plan_spec_scope_hash_and_micro_plan() -> None:
    plan = PlanSpec(
        plan_id="p-1",
        job_id="job-1",
        base_commit="abc1234",
        files_to_modify=["src/auth.py"],
        preliminary_risk=RiskLevel.HIGH,
        permissions_requested={"read": ["src/auth.py"], "write": ["src/auth.py"]},
    )
    scope_hash = plan.compute_scope_hash()
    assert isinstance(scope_hash, str) and len(scope_hash) == 64

    # The same plan produces the exact same scope_hash
    plan_clone = PlanSpec(
        plan_id="p-1",
        job_id="job-1",
        base_commit="abc1234",
        files_to_modify=["src/auth.py"],
        preliminary_risk=RiskLevel.HIGH,
        permissions_requested={"read": ["src/auth.py"], "write": ["src/auth.py"]},
    )
    assert plan_clone.compute_scope_hash() == scope_hash

    # MicroPlan conversion
    micro = MicroPlan(
        job_id="job-fast",
        base_commit="abc1234",
        target_file="src/utils.py",
        operation="modify",
        test_command="pytest tests/test_utils.py",
    )
    converted = micro.to_plan_spec()
    assert converted.files_to_modify == ["src/utils.py"]
    assert converted.preliminary_risk == RiskLevel.LOW


def test_patch_set_integrity_and_metrics() -> None:
    f1 = FilePatch(
        path="src/calc.py",
        operation=PatchOperation.MODIFY,
        patch=(
            "--- a/src/calc.py\n+++ b/src/calc.py\n@@ -1,2 +1,3 @@\n+def add(a, b): return a + b\n"
        ),
        sha256_before="1" * 64,
        sha256_after="2" * 64,
    )
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="abc1234",
        files=[f1],
    )
    assert patch_set.total_files == 1
    assert patch_set.total_diff_lines == 1
    assert not patch_set.has_mode_changes
    assert patch_set.affected_paths == {"src/calc.py"}


def test_event_hash_chaining_and_tamper_detection() -> None:
    e1 = Event.create(
        job_id="job-1",
        actor=EventActor.JOB_CONTROLLER,
        state="IDLE",
        event_name=EventName.TASK_CREATED,
        payload={"task": "Fix bug in calculation"},
        prev_hash=GENESIS_HASH,
    )
    assert e1.verify_integrity(expected_prev_hash=GENESIS_HASH)

    e2 = Event.create(
        job_id="job-1",
        actor=EventActor.ROUTER,
        state="ROUTING",
        event_name=EventName.ROUTE_SELECTED,
        payload={"intent": "DIRECT_WORKER_CODE", "confidence": 0.95},
        prev_hash=e1.event_hash,
    )
    assert e2.verify_integrity(expected_prev_hash=e1.event_hash)

    # Tampered event fails verification
    tampered_e2 = e2.model_copy(update={"payload": {"intent": "PLANNED_CODE"}})
    assert not tampered_e2.verify_integrity(expected_prev_hash=e1.event_hash)

    # Broken chain fails verification
    assert not e2.verify_integrity(expected_prev_hash="wrong_prev_hash" + "0" * 50)
