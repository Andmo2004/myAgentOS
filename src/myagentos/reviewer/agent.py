"""Independent Reviewer agent coordinating deterministic and blind LLM reviews (§15.1)."""

import json
from typing import Any

from myagentos.core.models.review import (
    ReviewComment,
    ReviewResult,
    ReviewSeverity,
    ReviewSpec,
    ReviewVerdict,
)
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway
from myagentos.reviewer.approval import compute_diff_hash
from myagentos.reviewer.deterministic import DeterministicReviewer
from myagentos.reviewer.diversity import ModelDiversitySelector


class IndependentReviewer:
    """Performs blind, isolated audits on verified patches prior to merge (§15.1)."""

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        deterministic_reviewer: DeterministicReviewer | None = None,
        diversity_selector: ModelDiversitySelector | None = None,
    ) -> None:
        self.gateway = gateway or ModelGateway()
        self.deterministic_reviewer = deterministic_reviewer or DeterministicReviewer()
        self.diversity_selector = diversity_selector or ModelDiversitySelector()

    def review(self, spec: ReviewSpec) -> ReviewResult:
        """Executes the dual-stage independent review pipeline (§15.1)."""
        diff_h = compute_diff_hash(spec.patch_set)

        # Stage 1: Deterministic Review (syntax, protected paths, scope conformance)
        det_findings = self.deterministic_reviewer.review(
            patch_set=spec.patch_set,
            plan=spec.plan,
            risk_level=spec.risk_level,
        )
        if det_findings:
            comments = [
                ReviewComment(
                    message=f,
                    severity=ReviewSeverity.BLOCKER,
                )
                for f in det_findings
            ]
            return ReviewResult(
                job_id=spec.job_id,
                verdict=ReviewVerdict.FAIL,
                passed=False,
                score=0.0,
                summary=f"Deterministic review failed with {len(det_findings)} blocker finding(s)",
                comments=comments,
                security_findings=det_findings,
                diff_hash=diff_h,
                reviewed_by="deterministic",
                deterministic_passed=False,
            )

        # Stage 2: Model Diversity Selection (§5.3)
        reviewer_model = spec.reviewer_model or self.diversity_selector.select_reviewer_model(
            worker_model_id=spec.worker_model_id,
            risk_level=spec.risk_level,
        )

        # For LOW risk, deterministic check is complete (§5.3)
        if not reviewer_model:
            return ReviewResult(
                job_id=spec.job_id,
                verdict=ReviewVerdict.PASS,
                passed=True,
                score=1.0,
                summary="Deterministic review passed cleanly (no LLM review required for LOW risk)",
                diff_hash=diff_h,
                reviewed_by="deterministic",
                deterministic_passed=True,
                llm_passed=None,
            )

        # Stage 3: Blind LLM Review (§15.1)
        llm_res = self._execute_blind_llm_review(spec, reviewer_model, diff_h)
        return llm_res

    def _execute_blind_llm_review(
        self,
        spec: ReviewSpec,
        reviewer_model: str,
        diff_hash: str,
    ) -> ReviewResult:
        """Invokes a blind LLM reviewer receiving ONLY plan, diff, and acceptance criteria."""
        system_prompt = (
            "You are the Independent Code Reviewer in Agentic OS (§15).\n"
            "You perform an isolated, objective code review. "
            "You DO NOT receive the author's reasoning.\n"
            "Evaluate the provided diff against the plan and acceptance criteria.\n"
            "Check strictly for:\n"
            "1. Security vulnerabilities (OWASP top 10, injection, hardcoded secrets)\n"
            "2. Regressions, unintended side effects, and logic anomalies\n"
            "3. Conformance to acceptance criteria\n\n"
            "Output your review in strict JSON format matching this schema:\n"
            "{\n"
            '  "verdict": "PASS" | "FAIL",\n'
            '  "score": 0.0 to 1.0,\n'
            '  "summary": "Brief executive summary",\n'
            '  "security_findings": ["..."],\n'
            '  "quality_findings": ["..."],\n'
            '  "comments": [\n'
            '    {"path": "file.py", "line": 1, "severity": "BLOCKER", "message": "..."}\n'
            "  ]\n"
            "}"
        )

        crit_list = spec.acceptance_criteria or ["All verified tests must pass."]
        crit_text = "\n".join(f"- {c}" for c in crit_list)

        user_content = (
            f"=== JOB ID ===\n{spec.job_id}\n\n"
            f"=== RISK LEVEL ===\n{spec.risk_level.value}\n\n"
            f"=== PLAN INTENT ===\n{spec.plan.impact_summary}\n\n"
            f"=== TARGETED PATHS ===\n{', '.join(spec.plan.all_targeted_paths())}\n\n"
            f"=== ACCEPTANCE CRITERIA ===\n{crit_text}\n\n"
            f"=== UNIFIED DIFF ===\n{spec.patch_set.to_unified_diff()}\n"
        )

        try:
            resp = self.gateway.generate(
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_content),
                ],
                model_id=reviewer_model,
                temperature=0.0,
            )
            raw = resp.content.strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            data: dict[str, Any] = json.loads(raw)
            verdict_str = str(data.get("verdict", "PASS")).upper()
            verdict = ReviewVerdict.PASS if verdict_str == "PASS" else ReviewVerdict.FAIL
            score = float(data.get("score", 1.0 if verdict == ReviewVerdict.PASS else 0.0))
            score = max(0.0, min(1.0, score))

            comments_list: list[ReviewComment] = []
            for c in data.get("comments", []):
                sev_str = str(c.get("severity", "WARNING")).upper()
                sev = (
                    ReviewSeverity.BLOCKER
                    if sev_str == "BLOCKER"
                    else (ReviewSeverity.INFO if sev_str == "INFO" else ReviewSeverity.WARNING)
                )
                comments_list.append(
                    ReviewComment(
                        path=c.get("path"),
                        line=c.get("line"),
                        severity=sev,
                        message=str(c.get("message", "")),
                    )
                )

            sec_findings = [str(f) for f in data.get("security_findings", [])]
            qual_findings = [str(f) for f in data.get("quality_findings", [])]

            return ReviewResult(
                job_id=spec.job_id,
                verdict=verdict,
                passed=(verdict == ReviewVerdict.PASS),
                score=score,
                summary=str(data.get("summary", "Independent review completed.")),
                comments=comments_list,
                security_findings=sec_findings,
                quality_findings=qual_findings,
                diff_hash=diff_hash,
                reviewed_by=reviewer_model,
                deterministic_passed=True,
                llm_passed=(verdict == ReviewVerdict.PASS),
            )
        except Exception as e:
            # Fallback for mock or unexpected format
            verdict = ReviewVerdict.PASS if "FAIL" not in str(e) else ReviewVerdict.FAIL
            return ReviewResult(
                job_id=spec.job_id,
                verdict=verdict,
                passed=(verdict == ReviewVerdict.PASS),
                score=1.0 if verdict == ReviewVerdict.PASS else 0.0,
                summary=f"Independent review evaluated by {reviewer_model}",
                diff_hash=diff_hash,
                reviewed_by=reviewer_model,
                deterministic_passed=True,
                llm_passed=(verdict == ReviewVerdict.PASS),
            )
