"""Tests for Project Continuation Audit (PCA) domain models."""

from typing import cast

import pytest

from myagentos.continuity.models import (
    ArchitectureMap,
    BaselineCheckResult,
    ContinuationFreshness,
    ContinuationFreshnessState,
    ContinuationReport,
    ContinuationStep,
    DiagnosticType,
    EntrypointInfo,
    EvidenceItem,
    EvidenceTier,
    Finding,
    FindingCode,
    FindingReportItem,
    FindingSeverity,
    FindingStatus,
    ModuleInfo,
    PathConstraint,
    ProjectBaseline,
    ProjectSnapshot,
    SuggestedFirstJob,
    UnresolvedQuestion,
    WorkingTreeState,
)
from myagentos.core.models.failure import FailureCode
from myagentos.core.models.risk import RiskLevel


def test_taxonomy_separation() -> None:
    """Ensure FindingCode, FailureCode, and RiskLevel are decoupled."""
    # FindingCode is about repository state
    assert FindingCode.TEST_FAILURE.value == "TEST_FAILURE"
    assert FindingCode.SECRET_DETECTED.value == "SECRET_DETECTED"
    assert FindingCode.BUILD_FAILURE.value == "BUILD_FAILURE"

    # FailureCode is about runtime agent OS failures
    assert FailureCode.TEST_FAILURE.value == "TEST_FAILURE"
    assert FailureCode.CONTEXT_MISSING.value == "CONTEXT_MISSING"

    # Types are distinct enums
    assert cast(object, type(FindingCode.TEST_FAILURE)) is not cast(
        object, type(FailureCode.TEST_FAILURE)
    )

    # FindingSeverity vs RiskLevel
    assert FindingSeverity.BLOCKER.value == "BLOCKER"
    assert FindingSeverity.HIGH.value == "HIGH"
    assert RiskLevel.HIGH.value == "HIGH"
    assert cast(object, type(FindingSeverity.HIGH)) is not cast(object, type(RiskLevel.HIGH))


def test_finding_immutability_and_confidence() -> None:
    """Verify Finding model properties, defaults, and validation."""
    evidence = EvidenceItem(
        kind=EvidenceTier.OBSERVED,
        source="tests/unit/test_auth.py",
        command="pytest",
        anchor="L42",
        observed_value="AssertionError",
        expected_value="200 OK",
    )
    finding = Finding(
        finding_id="F-001",
        code=FindingCode.TEST_FAILURE,
        severity=FindingSeverity.HIGH,
        title="Auth test failure",
        summary="Test test_login failed with 401 instead of 200",
        evidence=[evidence],
        confidence=0.95,
    )

    assert finding.finding_id == "F-001"
    assert finding.status == FindingStatus.OPEN
    assert finding.confidence == 0.95
    assert len(finding.evidence) == 1
    assert finding.evidence[0].kind == EvidenceTier.OBSERVED

    # Immutability check
    with pytest.raises(Exception):
        setattr(finding, "title", "Modified")

    # Confidence validation bounds [0.0, 1.0]
    with pytest.raises(ValueError):
        Finding(
            finding_id="F-002",
            code=FindingCode.DEAD_CODE,
            severity=FindingSeverity.LOW,
            title="Dead code",
            summary="Unused module",
            confidence=1.5,
        )


def test_snapshot_deterministic_hashing() -> None:
    """Verify ProjectSnapshot computes deterministic SHA-256 digests."""
    working_tree = WorkingTreeState(
        clean=True,
        content_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    snapshot1 = ProjectSnapshot(
        snapshot_id="snap-123",
        repository="myAgentOS",
        base_commit="c833c05",
        branch="main",
        working_tree=working_tree,
        toolchain_fingerprint={"python": "3.12.12"},
        dependency_lock_hashes={"uv.lock": "abc123hash"},
    )
    snapshot2 = ProjectSnapshot(
        snapshot_id="snap-123",
        repository="myAgentOS",
        base_commit="c833c05",
        branch="main",
        working_tree=working_tree,
        toolchain_fingerprint={"python": "3.12.12"},
        dependency_lock_hashes={"uv.lock": "abc123hash"},
    )

    hash1 = snapshot1.calculate_snapshot_hash()
    hash2 = snapshot2.calculate_snapshot_hash()
    assert hash1 == hash2
    assert len(hash1) == 64

    # Changing base commit changes the hash
    snapshot3 = ProjectSnapshot(
        snapshot_id="snap-123",
        repository="myAgentOS",
        base_commit="different_commit",
        branch="main",
        working_tree=working_tree,
        toolchain_fingerprint={"python": "3.12.12"},
        dependency_lock_hashes={"uv.lock": "abc123hash"},
    )
    assert snapshot3.calculate_snapshot_hash() != hash1


def test_architecture_and_baseline_hashing() -> None:
    """Verify ArchitectureMap and ProjectBaseline hashing."""
    arch = ArchitectureMap(
        modules=[
            ModuleInfo(
                id="core",
                path="src/myagentos/core",
                public_symbols=["Event", "RiskLevel"],
                dependencies=[],
                dependents=["fsm"],
            )
        ],
        entrypoints=[EntrypointInfo(path="src/myagentos/cli.py", symbol="main", kind="CLI")],
        languages={"python": 1.0},
        frameworks=["pydantic", "pytest"],
    )
    arch_hash = arch.calculate_architecture_hash()
    assert len(arch_hash) == 64

    baseline = ProjectBaseline(
        snapshot_id="snap-123",
        checks=[
            BaselineCheckResult(
                check_type=DiagnosticType.UNIT_TEST,
                command="pytest",
                exit_code=0,
                duration_ms=450,
                status="PASS",
                stdout_hash="stdout_hash_123",
                stderr_hash="stderr_hash_123",
            )
        ],
    )
    base_hash = baseline.calculate_baseline_hash()
    assert len(base_hash) == 64


def test_continuation_report_and_freshness() -> None:
    """Verify ContinuationReport serialization, hashing, and freshness."""
    step = ContinuationStep(
        step_id="STEP-001",
        title="Resolve broken config",
        objective="Fix environment variables in config loader",
        prerequisites=["verify .env.example exists"],
        affected_findings=["F-001"],
        affected_paths=["src/config.py"],
        validation="pytest tests/test_config.py",
    )
    first_job = SuggestedFirstJob(
        objective="Fix environment variable validation",
        scope=["src/config.py", "tests/test_config.py"],
    )

    report = ContinuationReport(
        summary="Repository has 1 broken test in config loader",
        current_state="Typecheck passes, unit tests fail on config.",
        architecture_summary="Modular Python project using Pydantic.",
        working_area=["src/config.py"],
        known_good=["src/core/**", "tests/test_core.py"],
        known_broken=["src/config.py"],
        findings=[
            FindingReportItem(
                finding_id="F-001",
                explanation="Missing default port in config",
                impact="Test test_default_config fails",
                evidence_refs=["tests/test_config.py:L15"],
            )
        ],
        blockers=["F-001"],
        unresolved_questions=[
            UnresolvedQuestion(
                question="Is port 8000 or 8080 canonical?",
                reason="README states 8080, code uses 8000",
            )
        ],
        recommended_next_steps=[step],
        do_not_touch_yet=[
            PathConstraint(
                path="src/legacy/**",
                reason="Scheduled for deprecation in v2.3",
            )
        ],
        suggested_first_task=first_job,
    )

    report_hash = report.calculate_report_hash()
    assert len(report_hash) == 64

    # Freshness model
    freshness = ContinuationFreshness(
        base_commit="c833c05",
        working_tree_hash="hash123",
        dependency_hash="dephash123",
        architecture_hash="archhash123",
        policy_version="1.0",
        state=ContinuationFreshnessState.VALID,
    )
    assert freshness.state == ContinuationFreshnessState.VALID
    assert freshness.stale_reason is None
