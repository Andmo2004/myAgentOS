"""Unit tests for Independent Reviewer, Deterministic Checks, and Diff Approval (§15)."""

from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.review import (
    ReviewSpec,
    ReviewVerdict,
)
from myagentos.core.models.risk import RiskLevel
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.gateway.registry import ModelEntry, ModelRegistry
from myagentos.reviewer.agent import IndependentReviewer
from myagentos.reviewer.approval import DiffApprovalManager, compute_diff_hash
from myagentos.reviewer.deterministic import DeterministicReviewer
from myagentos.reviewer.diversity import ModelDiversitySelector


def _make_dummy_plan(targeted_paths: list[str]) -> PlanSpec:
    return PlanSpec(
        plan_id="plan-test-1",
        job_id="job-test-1",
        base_commit="head",
        preliminary_risk=RiskLevel.LOW,
        impact_summary="Update calculation logic",
        files_to_modify=targeted_paths,
    )


def test_deterministic_reviewer_clean_patch() -> None:
    """Passes cleanly when diff conforms to scope and has no violations."""
    det = DeterministicReviewer()
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/calc.py",
                operation=PatchOperation.MODIFY,
                patch="VALUE = 42\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    plan = _make_dummy_plan(["src/calc.py"])
    findings = det.review(patch_set, plan, RiskLevel.LOW)
    assert len(findings) == 0


def test_deterministic_reviewer_conflict_markers() -> None:
    """Detects unresolved merge conflict markers inside a patch."""
    det = DeterministicReviewer()
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/calc.py",
                operation=PatchOperation.MODIFY,
                patch="<<<<<<< HEAD\nVALUE = 1\n=======\nVALUE = 2\n>>>>>>> branch\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    plan = _make_dummy_plan(["src/calc.py"])
    findings = det.review(patch_set, plan, RiskLevel.LOW)
    assert any("conflict markers" in f for f in findings)


def test_deterministic_reviewer_scope_violation() -> None:
    """Flags out-of-scope files that were not declared in the approved plan (§15.1)."""
    det = DeterministicReviewer()
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/other.py",
                operation=PatchOperation.MODIFY,
                patch="SECRET = 1\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    plan = _make_dummy_plan(["src/calc.py"])
    findings = det.review(patch_set, plan, RiskLevel.LOW)
    assert any("Out-of-scope" in f for f in findings)


def test_deterministic_reviewer_protected_path_alteration() -> None:
    """Flags modifications to integrity-protected paths (§13.3, §15.1)."""
    det = DeterministicReviewer(protected_paths=["tests/conftest.py"])
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="head",
        files=[
            FilePatch(
                path="tests/conftest.py",
                operation=PatchOperation.MODIFY,
                patch="# tampered\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    plan = _make_dummy_plan(["tests/conftest.py"])
    findings = det.review(patch_set, plan, RiskLevel.LOW)
    assert any("protected path" in f for f in findings)


def test_deterministic_reviewer_sensitive_path_under_low_risk() -> None:
    """Flags sensitive path modifications under LOW risk level (§5.2)."""
    det = DeterministicReviewer()
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/auth/login.py",
                operation=PatchOperation.MODIFY,
                patch="def login(): pass\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    plan = _make_dummy_plan(["src/auth/login.py"])
    findings = det.review(patch_set, plan, RiskLevel.LOW)
    assert any("Sensitive path" in f for f in findings)


def test_model_diversity_selection() -> None:
    """Verifies model and provider diversity selection across risk levels (§5.3)."""
    registry = ModelRegistry()
    registry.register(ModelEntry(model_id="gpt-4o", provider="openai", platform="api"))
    registry.register(ModelEntry(model_id="gemini-1.5-pro", provider="google", platform="api"))
    registry.register(ModelEntry(model_id="gpt-4o-mini", provider="openai", platform="api"))

    selector = ModelDiversitySelector(registry=registry)

    # LOW: None (deterministic only)
    assert selector.select_reviewer_model("gpt-4o", RiskLevel.LOW) is None

    # MEDIUM: Different model
    med_model = selector.select_reviewer_model("gpt-4o", RiskLevel.MEDIUM)
    assert med_model != "gpt-4o"
    assert med_model in ("gemini-1.5-pro", "gpt-4o-mini")

    # HIGH / CRITICAL: Different provider when available
    high_model = selector.select_reviewer_model("gpt-4o", RiskLevel.HIGH)
    assert high_model == "gemini-1.5-pro"  # Different provider (google != openai)


def test_blind_llm_reviewer_invocation() -> None:
    """Verifies that the reviewer is invoked blindly and parses structured verdicts (§15.1)."""
    captured_messages: list[LLMMessage] = []

    class MockReviewAdapter(ProviderAdapter):
        def generate(
            self,
            messages: list[LLMMessage],
            model_id: str,
            temperature: float = 0.0,
            response_schema: type | None = None,
        ) -> LLMResponse:
            nonlocal captured_messages
            captured_messages = list(messages)
            content = (
                "{\n"
                '  "verdict": "PASS",\n'
                '  "score": 0.95,\n'
                '  "summary": "Implementation clean without security issues",\n'
                '  "security_findings": [],\n'
                '  "quality_findings": [],\n'
                '  "comments": []\n'
                "}"
            )
            return LLMResponse(
                content=content, model_id=model_id, input_tokens=50, output_tokens=30
            )

    gateway = ModelGateway()
    gateway.register_adapter("mock", MockReviewAdapter())

    reviewer = IndependentReviewer(gateway=gateway)
    patch_set = PatchSet(
        job_id="job-rev-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/calc.py",
                operation=PatchOperation.MODIFY,
                patch="VALUE = 100\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    spec = ReviewSpec(
        job_id="job-rev-1",
        patch_set=patch_set,
        plan=_make_dummy_plan(["src/calc.py"]),
        risk_level=RiskLevel.MEDIUM,
        worker_model_id="mock-worker",
    )
    result = reviewer.review(spec)

    assert result.passed is True
    assert result.verdict == ReviewVerdict.PASS
    assert result.score == 0.95
    assert result.deterministic_passed is True
    assert result.llm_passed is True

    # Verify blindness: worker reasoning is not present in prompts
    all_prompt_text = " ".join(m.content for m in captured_messages)
    assert "thought" not in all_prompt_text
    assert "scratchpad" not in all_prompt_text
    assert "VALUE = 100" in all_prompt_text


def test_diff_approval_manager_lifecycle() -> None:
    """Verifies diff hash binding and invalidation on modification (§8.4, §15.2)."""
    mgr = DiffApprovalManager()
    patch_set_1 = PatchSet(
        job_id="job-diff-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/calc.py",
                operation=PatchOperation.MODIFY,
                patch="VALUE = 10\n",
                sha256_before="abc",
                sha256_after="def",
            )
        ],
    )
    h1 = compute_diff_hash(patch_set_1)
    approval = mgr.create_approval("job-diff-1", patch_set_1, approved=True)
    assert approval.diff_hash == h1

    # Validate approval matches patch_set_1
    ok, err = mgr.validate_approval(approval, patch_set_1)
    assert ok is True
    assert err is None

    # Alter patch set -> prior approval must be invalidated
    patch_set_2 = PatchSet(
        job_id="job-diff-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/calc.py",
                operation=PatchOperation.MODIFY,
                patch="VALUE = 999\n",
                sha256_before="abc",
                sha256_after="ghi",
            )
        ],
    )
    ok_alt, err_alt = mgr.validate_approval(approval, patch_set_2)
    assert ok_alt is False
    assert "Diff hash mismatch" in str(err_alt)
