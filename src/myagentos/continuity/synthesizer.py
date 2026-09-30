"""Continuity Analyst synthesizer generating structured reports and human markdown (§16-19, §37)."""

import json
from typing import Any

from myagentos.continuity.models import (
    ArchitectureMap,
    ContinuationReport,
    ContinuationStep,
    Finding,
    FindingCode,
    FindingReportItem,
    FindingSeverity,
    PathConstraint,
    ProjectBaseline,
    ProjectSnapshot,
    SuggestedFirstJob,
    UnresolvedQuestion,
)
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway

CONTINUITY_SYSTEM_PROMPT = """You are the continuity analyst.

Your task is to transform repository evidence into an actionable continuation context.

Rules:
1. Never invent repository facts.
2. Every substantive claim must reference an evidence item.
3. Distinguish observed facts from inference.
4. Preserve unknowns explicitly.
5. Do not propose permissions.
6. Do not propose secrets.
7. Do not modify policy.
8. Do not claim a fix has been applied.
9. Prefer exact paths, symbols, and commands.
10. Produce structured output matching the ContinuationReport schema.
"""


def build_analyst_prompts(
    snapshot: ProjectSnapshot,
    architecture: ArchitectureMap,
    findings: list[Finding],
    baseline: ProjectBaseline | None = None,
) -> tuple[str, str]:
    """Prepares system and user prompts for the continuity analyst (§16, §37)."""
    evidence_payload: dict[str, Any] = {
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "repository": snapshot.repository,
            "base_commit": snapshot.base_commit,
            "branch": snapshot.branch,
            "working_tree_clean": snapshot.working_tree.clean,
            "uncommitted_files": snapshot.working_tree.uncommitted_files,
            "toolchain": snapshot.toolchain_fingerprint,
            "dependency_locks": list(snapshot.dependency_lock_hashes.keys()),
        },
        "architecture": {
            "languages": architecture.languages,
            "frameworks": architecture.frameworks,
            "entrypoints": [e.model_dump() for e in architecture.entrypoints],
            "modules_count": len(architecture.modules),
        },
        "findings": [
            {
                "id": f.finding_id,
                "code": f.code,
                "severity": f.severity,
                "title": f.title,
                "summary": f.summary,
                "evidence": [e.model_dump() for e in f.evidence],
            }
            for f in findings
        ],
    }
    if baseline:
        evidence_payload["baseline"] = [
            {
                "check": c.check_type,
                "command": c.command,
                "status": c.status,
                "exit_code": c.exit_code,
            }
            for c in baseline.checks
        ]

    user_prompt = (
        "Synthesize the following deterministic repository evidence into a ContinuationReport:\n"
        f"```json\n{json.dumps(evidence_payload, indent=2)}\n```"
    )
    return CONTINUITY_SYSTEM_PROMPT, user_prompt


def generate_deterministic_synthesis(
    snapshot: ProjectSnapshot,
    architecture: ArchitectureMap,
    findings: list[Finding],
    baseline: ProjectBaseline | None = None,
) -> ContinuationReport:
    """Generates an authoritative, deterministic report directly from facts (§2.2)."""
    blocker_findings = [f for f in findings if f.severity == FindingSeverity.BLOCKER]
    high_findings = [f for f in findings if f.severity == FindingSeverity.HIGH]

    # Categorize operational state
    known_good: list[str] = []
    known_broken: list[str] = []

    if baseline:
        for c in baseline.checks:
            if c.status == "PASS":
                known_good.append(f"{c.check_type}: {c.command}")
            else:
                known_broken.append(f"{c.check_type}: {c.command} (exit {c.exit_code})")

    for f in findings:
        if f.severity in (FindingSeverity.BLOCKER, FindingSeverity.HIGH):
            for ev in f.evidence:
                if ev.source not in known_broken:
                    known_broken.append(ev.source)

    for m in architecture.modules:
        if not any(m.path in b for b in known_broken):
            known_good.append(m.path)

    # Convert findings to report items
    finding_items: list[FindingReportItem] = []
    for f in findings:
        refs: list[str] = []
        for e in f.evidence:
            ref = e.source
            if e.anchor:
                ref = f"{ref}:{e.anchor}"
            refs.append(ref)
        finding_items.append(
            FindingReportItem(
                finding_id=f.finding_id,
                explanation=f.summary,
                impact=f.impact or f"Discovered condition with severity {f.severity.value}",
                evidence_refs=refs,
            )
        )

    # Next steps by dependency (§26)
    next_steps: list[ContinuationStep] = []
    step_num = 1

    # Address blockers / high first
    for f in blocker_findings + high_findings:
        step_id = f"STEP-{step_num:03d}"
        paths = [e.source for e in f.evidence]
        validation = "Re-run static discovery and baseline checks"
        next_steps.append(
            ContinuationStep(
                step_id=step_id,
                title=f"Resolve {f.code.value} in {paths[0] if paths else 'repository'}",
                objective=f.summary,
                affected_findings=[f.finding_id],
                affected_paths=paths,
                risk_hint="MEDIUM",
                validation=validation,
            )
        )
        step_num += 1

    if not next_steps:
        next_steps.append(
            ContinuationStep(
                step_id="STEP-001",
                title="Proceed with proposed development tasks",
                objective="Baseline is green with no blocker findings.",
                validation="Run test suite before and after change",
            )
        )

    # Sensitive paths to avoid modifying immediately
    do_not_touch: list[PathConstraint] = []
    for f in findings:
        if f.code == FindingCode.SECRET_DETECTED:
            for ev in f.evidence:
                do_not_touch.append(
                    PathConstraint(
                        path=ev.source,
                        reason="Contains potential unredacted secret; requires careful handling",
                    )
                )

    # Suggested first job (§27)
    first_step = next_steps[0]
    suggested_job = SuggestedFirstJob(
        intent="PLANNED_CODE",
        objective=first_step.objective,
        scope=first_step.affected_paths,
        prerequisites=first_step.prerequisites,
        acceptance=[first_step.validation],
        risk_hint=first_step.risk_hint,
    )

    unresolved: list[UnresolvedQuestion] = []
    if not snapshot.working_tree.clean:
        unresolved.append(
            UnresolvedQuestion(
                question="Should uncommitted changes be preserved or reset?",
                reason="Working tree was dirty at snapshot time",
            )
        )

    langs_desc = ", ".join(f"{k} ({int(v * 100)}%)" for k, v in architecture.languages.items())
    frameworks_desc = (
        ", ".join(architecture.frameworks) if architecture.frameworks else "None detected"
    )

    c_short = snapshot.base_commit[:7] if len(snapshot.base_commit) >= 7 else snapshot.base_commit
    summary_text = (
        f"Project continuation audit for {snapshot.repository} at commit {c_short}. "
        f"Identified {len(findings)} findings ({len(blocker_findings)} blockers)."
    )
    current_state_text = (
        f"Repository has {len(snapshot.tracked_files)} tracked files. "
        f"Working tree is {'CLEAN' if snapshot.working_tree.clean else 'DIRTY'}."
    )
    arch_summary_text = f"Languages: {langs_desc or 'unspecified'}. Frameworks: {frameworks_desc}."

    report = ContinuationReport(
        summary=summary_text,
        current_state=current_state_text,
        architecture_summary=arch_summary_text,
        working_area=[m.path for m in architecture.modules[:5]],
        known_good=known_good[:10],
        known_broken=known_broken[:10],
        findings=finding_items,
        blockers=[b.finding_id for b in blocker_findings],
        unresolved_questions=unresolved,
        recommended_next_steps=next_steps,
        do_not_touch_yet=do_not_touch,
        suggested_first_task=suggested_job,
    )

    # Controller seals context digest (§31)
    context_digest = report.calculate_report_hash()
    return report.model_copy(update={"context_digest": context_digest})


def synthesize_continuation_report(
    snapshot: ProjectSnapshot,
    architecture: ArchitectureMap,
    findings: list[Finding],
    baseline: ProjectBaseline | None = None,
    gateway: ModelGateway | None = None,
    model_id: str = "mock-default",
) -> ContinuationReport:
    """Synthesizes the ContinuationReport, using deterministic synthesis or LLM (§16, §17)."""
    # Deterministic facts first
    report = generate_deterministic_synthesis(
        snapshot=snapshot,
        architecture=architecture,
        findings=findings,
        baseline=baseline,
    )

    # If an LLM gateway is available, it can augment the summary and human explanations
    if gateway is not None:
        try:
            sys_prompt, user_prompt = build_analyst_prompts(
                snapshot=snapshot,
                architecture=architecture,
                findings=findings,
                baseline=baseline,
            )
            messages = [
                LLMMessage(role="system", content=sys_prompt),
                LLMMessage(role="user", content=user_prompt),
            ]
            resp = gateway.generate(
                messages=messages,
                model_id=model_id,
            )
            if resp.content and len(resp.content.strip()) > 20:
                report = report.model_copy(
                    update={"summary": resp.content.strip().split("\n\n")[0]}
                )
        except Exception:
            # Fall back safely to deterministic synthesis
            pass

    # Seal report hash deterministically (§31)
    digest = report.calculate_report_hash()
    return report.model_copy(update={"context_digest": digest})


def render_continuation_markdown(
    snapshot: ProjectSnapshot,
    architecture: ArchitectureMap,
    report: ContinuationReport,
    baseline: ProjectBaseline | None = None,
) -> str:
    """Renders CONTINUATION_CONTEXT.md following the human format in §19."""
    lines: list[str] = [
        "# Project Continuation Context",
        "",
        "## Snapshot",
        "",
        f"- Repository: {snapshot.repository}",
        f"- Commit: {snapshot.base_commit}",
        f"- Branch: {snapshot.branch}",
        f"- Working tree: {'CLEAN' if snapshot.working_tree.clean else 'DIRTY'}",
        f"- Generated at: {snapshot.created_at.isoformat()}",
        f"- Context version: {snapshot.policy_version}",
        f"- Context hash: {report.context_digest or 'UNSEALED'}",
        "",
        "## Executive Summary",
        "",
        report.summary,
        "",
        "## Project Shape",
        "",
        "### Stack",
        "",
    ]
    for lang, ratio in architecture.languages.items():
        lines.append(f"- {lang}: {int(ratio * 100)}%")
    if architecture.frameworks:
        lines.append(f"- Frameworks: {', '.join(architecture.frameworks)}")
    lines.append("")

    lines.append("### Entrypoints")
    lines.append("")
    if architecture.entrypoints:
        for e in architecture.entrypoints:
            lines.append(f"- `{e.path}` ({e.kind})")
    else:
        lines.append("No explicit entrypoints identified.")
    lines.append("")

    lines.append("### Module Map")
    lines.append("")
    for m in architecture.modules[:10]:
        lines.append(f"- `{m.path}` ({len(m.public_symbols)} public symbols)")
    lines.append("")

    lines.append("## Current Operational State")
    lines.append("")
    if baseline and baseline.checks:
        for c in baseline.checks:
            lines.append(f"### {c.check_type}")
            lines.append(f"- Command: `{c.command}`")
            lines.append(f"- Status: **{c.status}** (exit code {c.exit_code}, {c.duration_ms}ms)")
            lines.append("")
    else:
        lines.append("No dynamic baseline checks executed (static-only audit).")
        lines.append("")

    lines.append("## Findings")
    lines.append("")
    if not report.findings:
        lines.append("No critical findings detected.")
    else:
        for f in report.findings:
            lines.append(f"### {f.finding_id}")
            lines.append(f"- Explanation: {f.explanation}")
            lines.append(f"- Impact: {f.impact}")
            if f.evidence_refs:
                lines.append(f"- Evidence: {', '.join(f.evidence_refs)}")
            lines.append("")

    lines.append("## Known Good")
    lines.append("")
    for item in report.known_good:
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Known Broken")
    lines.append("")
    if report.known_broken:
        for item in report.known_broken:
            lines.append(f"- {item}")
    else:
        lines.append("None identified.")
    lines.append("")

    lines.append("## Unknowns")
    lines.append("")
    if report.unresolved_questions:
        for q in report.unresolved_questions:
            lines.append(f"- **{q.question}**: {q.reason}")
    else:
        lines.append("No blocking unknowns identified.")
    lines.append("")

    lines.append("## Recommended Continuation")
    lines.append("")
    for step in report.recommended_next_steps:
        lines.append(f"### {step.step_id} — {step.title}")
        lines.append(f"- Objective: {step.objective}")
        if step.affected_paths:
            lines.append(f"- Affected paths: {', '.join(step.affected_paths)}")
        lines.append(f"- Validation: `{step.validation}`")
        lines.append("")

    lines.append("## Do Not Touch Yet")
    lines.append("")
    if report.do_not_touch_yet:
        for p in report.do_not_touch_yet:
            lines.append(f"- `{p.path}`: {p.reason}")
    else:
        lines.append("No sensitive path exclusions active.")
    lines.append("")

    lines.append("## Suggested First Job")
    lines.append("")
    lines.append(f"- Intent: `{report.suggested_first_task.intent}`")
    lines.append(f"- Objective: {report.suggested_first_task.objective}")
    if report.suggested_first_task.scope:
        lines.append(f"- Scope: {', '.join(report.suggested_first_task.scope)}")
    lines.append(f"- Acceptance: {', '.join(report.suggested_first_task.acceptance)}")
    lines.append("")

    return "\n".join(lines)
