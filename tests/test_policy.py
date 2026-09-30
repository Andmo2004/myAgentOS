"""Unit tests for the PolicyEngine, risk signals, and patch validation."""

from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel, RiskPhase
from myagentos.policy import PolicyEngine, detect_risk_signals


def test_detect_risk_signals_categories() -> None:
    # 1. Auth signal -> HIGH
    auth_sigs = detect_risk_signals(["src/auth/service.py"])
    assert len(auth_sigs) >= 1
    assert any(s.minimum_risk == RiskLevel.HIGH for s in auth_sigs)

    # 2. CI/CD signal -> CRITICAL
    ci_sigs = detect_risk_signals([".github/workflows/deploy.yml"])
    assert any(s.minimum_risk == RiskLevel.CRITICAL for s in ci_sigs)

    # 3. Protected test signal -> CRITICAL
    prot_sigs = detect_risk_signals(["tests/protected/test_security.py"])
    assert any(
        s.category == "protected_path" and s.minimum_risk == RiskLevel.CRITICAL for s in prot_sigs
    )

    # 4. Safe plain path -> no sensitive signals
    safe_sigs = detect_risk_signals(["src/math_helper.py"])
    assert len(safe_sigs) == 0


def test_policy_engine_assess_risk_monotonic() -> None:
    engine = PolicyEngine()

    # Safe single file starts as LOW
    assessment = engine.assess_risk(["src/hello.py"], current_risk=RiskLevel.LOW)
    assert assessment.level == RiskLevel.LOW
    assert assessment.phase == RiskPhase.FINAL

    # Introducing auth file escalates to HIGH
    assessment_auth = engine.assess_risk(["src/auth/login.py"], current_risk=RiskLevel.LOW)
    assert assessment_auth.level == RiskLevel.HIGH

    # If current_risk is already HIGH, evaluating a safe file preserves HIGH (monotonic invariant)
    assessment_mono = engine.assess_risk(["src/hello.py"], current_risk=RiskLevel.HIGH)
    assert assessment_mono.level == RiskLevel.HIGH


def test_policy_engine_validate_patch_rules() -> None:
    engine = PolicyEngine()

    plan = PlanSpec(
        plan_id="p-val",
        job_id="job-val",
        base_commit="commit-1",
        files_to_modify=["src/feature.py"],
        permissions_requested={
            "read": ["src/**"],
            "write": ["src/feature.py"],
            "execute": ["pytest"],
        },
    )
    token = engine.issue_capability_token(
        job_id="job-val",
        worker_id="w-1",
        plan=plan,
        risk_level=RiskLevel.LOW,
    )

    # 1. Valid patch
    valid_patch = PatchSet(
        job_id="job-val",
        base_commit="commit-1",
        files=[
            FilePatch(
                path="src/feature.py",
                operation=PatchOperation.MODIFY,
                patch="+print('hello')",
                sha256_before="1" * 64,
                sha256_after="2" * 64,
            )
        ],
    )
    is_valid, violations = engine.validate_patch(valid_patch, token)
    assert is_valid
    assert len(violations) == 0

    # 2. Path traversal violation
    traversal_patch = PatchSet(
        job_id="job-val",
        base_commit="commit-1",
        files=[
            FilePatch(
                path="../etc/passwd",
                operation=PatchOperation.MODIFY,
                patch="+bad",
                sha256_before="1" * 64,
                sha256_after="2" * 64,
            )
        ],
    )
    is_valid, violations = engine.validate_patch(traversal_patch, token)
    assert not is_valid
    assert any("path traversal" in v.lower() for v in violations)

    # 3. Unauthorized write scope violation
    scope_patch = PatchSet(
        job_id="job-val",
        base_commit="commit-1",
        files=[
            FilePatch(
                path="src/other.py",
                operation=PatchOperation.MODIFY,
                patch="+bad",
                sha256_before="1" * 64,
                sha256_after="2" * 64,
            )
        ],
    )
    is_valid, violations = engine.validate_patch(scope_patch, token)
    assert not is_valid
    assert any("outside authorized write scope" in v for v in violations)

    # 4. Protected path violation
    protected_patch = PatchSet(
        job_id="job-val",
        base_commit="commit-1",
        files=[
            FilePatch(
                path="conftest.py",
                operation=PatchOperation.MODIFY,
                patch="+bad",
                sha256_before="1" * 64,
                sha256_after="2" * 64,
            )
        ],
    )
    is_valid, violations = engine.validate_patch(protected_patch, token)
    assert not is_valid
    assert any("protected path" in v for v in violations)
