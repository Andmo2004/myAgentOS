"""Adversarial security and independence tests for Independent Reviewer (§15, AUD-013, AUD-014)."""

import json
from pathlib import Path

from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.review import (
    ReviewVerdict,
)
from myagentos.core.models.risk import RiskLevel
from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator
from myagentos.reviewer.deterministic import DeterministicReviewer


def test_aud_014_adversarial_protected_path_tampering_blocked() -> None:
    """AUD-014: Worker attempts to modify a protected test or harness file; review blocks merge."""
    det = DeterministicReviewer(protected_paths=["tests/test_auth.py", ".github/workflows/ci.yml"])

    # Worker crafts a patch altering protected test
    adversarial_patch = PatchSet(
        job_id="job-adv-1",
        base_commit="head",
        files=[
            FilePatch(
                path="tests/test_auth.py",
                operation=PatchOperation.MODIFY,
                patch="def test_auth(): assert True # bypassed\n",
                sha256_before="111",
                sha256_after="222",
            )
        ],
    )
    from myagentos.core.models.plan import PlanSpec

    plan = PlanSpec(
        plan_id="plan-adv-1",
        job_id="job-adv-1",
        base_commit="head",
        preliminary_risk=RiskLevel.MEDIUM,
        impact_summary="Fix auth test",
        files_to_modify=["tests/test_auth.py"],
    )

    findings = det.review(adversarial_patch, plan, RiskLevel.MEDIUM)
    assert len(findings) > 0
    assert any("protected path" in f for f in findings)


def test_aud_014_adversarial_out_of_scope_tampering_blocked() -> None:
    """AUD-014: Worker attempts to modify files outside declared and approved plan scope."""
    det = DeterministicReviewer()
    patch = PatchSet(
        job_id="job-adv-2",
        base_commit="head",
        files=[
            FilePatch(
                path="src/payments.py",
                operation=PatchOperation.MODIFY,
                patch="FEE = 0\n",
                sha256_before="aaa",
                sha256_after="bbb",
            )
        ],
    )
    from myagentos.core.models.plan import PlanSpec

    plan = PlanSpec(
        plan_id="plan-adv-2",
        job_id="job-adv-2",
        base_commit="head",
        preliminary_risk=RiskLevel.LOW,
        impact_summary="Update UI button",
        files_to_modify=["src/ui.py"],
    )

    findings = det.review(patch, plan, RiskLevel.LOW)
    assert len(findings) > 0
    assert any("Out-of-scope modification" in f for f in findings)


def test_aud_014_independent_reviewer_flags_security_flaw_and_heals(
    tmp_path: Path,
) -> None:
    """AUD-014: Blind reviewer detects hardcoded credential in patch, rejecting merge (§15.1)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    target = src_dir / "service.py"
    target.write_text("API_KEY = None\n")

    # Worker response: introduces hardcoded secret
    worker_resp = json.dumps(
        {
            "thought": "Using fixed secret for testing",
            "propose_patch": {
                "description": "Hardcode secret",
                "files": [
                    {
                        "path": "src/service.py",
                        "operation": "MODIFY",
                        "content": "API_KEY = 'sk-live-supersecret12345'\n",
                    }
                ],
            },
        }
    )

    # Reviewer response: rejects due to hardcoded credential
    reviewer_rejection = (
        "{\n"
        '  "verdict": "FAIL",\n'
        '  "score": 0.1,\n'
        '  "summary": "Hardcoded live API key found in source code",\n'
        '  "security_findings": ["Hardcoded secret detected: sk-live-supersecret12345"],\n'
        '  "comments": [\n'
        '    {"path": "src/service.py", "line": 1, "severity": "BLOCKER", '
        '"message": "Remove hardcoded credential"}\n'
        "  ]\n"
        "}"
    )

    class AdversarialGatewayAdapter(ProviderAdapter):
        def generate(
            self,
            messages: list[LLMMessage],
            model_id: str,
            temperature: float = 0.0,
            response_schema: type | None = None,
        ) -> LLMResponse:
            system_msg = messages[0].content if messages else ""
            if "Independent Code Reviewer" in system_msg:
                return LLMResponse(
                    content=reviewer_rejection,
                    model_id=model_id,
                    input_tokens=100,
                    output_tokens=60,
                )
            return LLMResponse(
                content=worker_resp,
                model_id=model_id,
                input_tokens=50,
                output_tokens=50,
            )

    gateway = ModelGateway()
    gateway.register_adapter("mock", AdversarialGatewayAdapter())

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        reviewer_model_id="mock",
        auto_approve=True,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(
        config=config,
        gateway=gateway,
    )

    result = orchestrator.run("/direct update service in src/service.py")

    # The pipeline must fail because the independent reviewer rejected the changes
    assert result.success is False
    assert result.final_state in (
        JobState.CANCELLED,
        JobState.FAILURE_CLASSIFY,
        JobState.WAIT_DIFF_APPROVAL,
    )
    assert result.review is not None
    assert result.review.verdict == ReviewVerdict.FAIL
    assert any("Hardcoded secret" in f for f in result.review.security_findings)

    # Target file in repo root must remain untouched!
    assert target.read_text() == "API_KEY = None\n"

    # Event store records REVIEW_REJECTED failure classification
    events = orchestrator.event_store.load_events(result.job_id)
    event_names = [e.event_name for e in events]
    assert "FAILURE_CLASSIFIED" in event_names
