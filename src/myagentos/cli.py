"""Command line interface for myagentos."""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from myagentos.benchmark import BenchmarkHarness, BenchmarkTask
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.core.store.state_projector import StateProjector
from myagentos.pipeline import PipelineConfig, PipelineOrchestrator
from myagentos.router.models import RoutingIntent
from myagentos.router.rules import LocalRouter

console = Console()


def cmd_route(prompt: str) -> None:
    router = LocalRouter()
    decision = router.route(prompt)

    table = Table(title="myagentos — Local Router v0 (§6)")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Intent", decision.intent.value)
    table.add_row("Preliminary Risk", decision.preliminary_risk.value)
    table.add_row("Confidence", f"{decision.confidence:.2f}")
    table.add_row("Matched Rule", decision.matched_rule)
    table.add_row("Cleaned Prompt", decision.cleaned_prompt)

    console.print(table)


def cmd_status(job_id: str) -> None:
    store = EventStore()
    projector = StateProjector(store)
    manifest = projector.load_manifest(job_id)

    if not manifest:
        console.print(f"[red]Job {job_id} not found.[/red]")
        sys.exit(1)

    table = Table(title=f"myagentos — Job Status: {job_id}")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Current State", manifest.current_state)
    table.add_row("Risk Level", manifest.risk_level.value)
    table.add_row("Base Commit", manifest.base_commit or "N/A")
    table.add_row("Active Plan", manifest.active_plan_id or "N/A")
    table.add_row("Total Events", str(manifest.total_events))
    table.add_row("Failures Encountered", str(manifest.failure_count))
    table.add_row("Last Event SHA-256", manifest.last_event_hash[:16] + "...")

    console.print(table)


def cmd_verify(job_id: str) -> None:
    store = EventStore()
    is_valid, reason = store.verify_integrity(job_id)

    if is_valid:
        console.print(f"[green]✓ Cryptographic event log for {job_id} is intact.[/green]")
    else:
        console.print(f"[red]✗ Cryptographic corruption detected: {reason}[/red]")
        sys.exit(1)


def cmd_benchmark() -> None:
    harness = BenchmarkHarness(store_dir=Path(".myagentos/bench_jobs"))
    tasks = [
        BenchmarkTask(
            task_id="t1-typo",
            prompt="/direct fix typo in documentation",
            target_files=["docs/readme.md"],
            expected_intent=RoutingIntent.DIRECT_WORKER_CODE,
            expected_risk=RiskLevel.LOW,
        ),
        BenchmarkTask(
            task_id="t2-auth",
            prompt="Refactor user session authentication and password reset",
            target_files=["src/auth/service.py", "src/auth/tokens.py"],
            expected_intent=RoutingIntent.PLANNED_CODE,
            expected_risk=RiskLevel.HIGH,
        ),
        BenchmarkTask(
            task_id="t3-false-direct",
            prompt="/direct change jwt token secret key",
            target_files=["src/auth/jwt.py"],
            expected_intent=RoutingIntent.PLANNED_CODE,  # Escalated due to high risk
            expected_risk=RiskLevel.HIGH,
        ),
    ]

    table = Table(title="myagentos — Baseline Benchmark Validation (§26, §28)")
    table.add_column("Task ID", style="cyan")
    table.add_column("Intent Match", style="green")
    table.add_column("False Direct?", style="magenta")
    table.add_column("Risk Monotonic?", style="blue")
    table.add_column("Final State", style="yellow")
    table.add_column("Duration (ms)", style="dim")
    table.add_column("Chain Intact?", style="bold green")

    for t in tasks:
        metric = harness.run_task(t)
        table.add_row(
            metric.task_id,
            "YES" if metric.intent_match else "NO",
            "YES (Violation)" if metric.false_direct else "NO (Safe)",
            "YES" if metric.risk_monotonically_preserved else "NO",
            metric.final_state.value,
            f"{metric.duration_seconds * 1000:.1f}",
            "VALID" if metric.hash_chain_intact else "CORRUPTED",
        )

    console.print(table)


def cmd_continue(
    action: str = "run",
    repo_path: str = ".",
    dynamic: bool = False,
) -> None:
    import json
    import subprocess
    import time

    from rich.markdown import Markdown

    from myagentos.continuity.discovery import run_static_discovery
    from myagentos.continuity.models import (
        BaselineCheckResult,
        DiagnosticType,
        FindingSeverity,
        ProjectBaseline,
    )
    from myagentos.continuity.snapshot import create_project_snapshot
    from myagentos.continuity.store import ContinuityStore
    from myagentos.continuity.synthesizer import synthesize_continuation_report

    root = Path(repo_path).resolve()
    store = ContinuityStore(root)
    project_id = root.name

    if action == "report":
        pdir = store.base_dir / project_id / "continuity"
        if not pdir.is_dir():
            console.print(
                f"[yellow]No continuation context for '{project_id}'."
                " Run `myagentos continue` first.[/yellow]"
            )
            return
        snaps = sorted(
            [d for d in pdir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not snaps or not (snaps[0] / "CONTINUATION_CONTEXT.md").is_file():
            console.print(f"[yellow]No CONTINUATION_CONTEXT.md found for '{project_id}'.[/yellow]")
            return
        md_text = (snaps[0] / "CONTINUATION_CONTEXT.md").read_text(encoding="utf-8")
        console.print(Markdown(md_text))
        return

    if action == "findings":
        pdir = store.base_dir / project_id / "continuity"
        snaps = (
            sorted(
                [d for d in pdir.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            if pdir.is_dir()
            else []
        )
        if not snaps or not (snaps[0] / "findings.json").is_file():
            console.print(
                f"[yellow]No findings found for '{project_id}'."
                " Run `myagentos continue` first.[/yellow]"
            )
            return

        findings_data = json.loads((snaps[0] / "findings.json").read_text(encoding="utf-8"))
        f_table = Table(title=f"Findings — {project_id} ({snaps[0].name})")
        f_table.add_column("ID", style="cyan")
        f_table.add_column("Severity", style="magenta")
        f_table.add_column("Code", style="bold")
        f_table.add_column("Title")
        for item in findings_data:
            sev = item.get("severity", "INFO")
            style = (
                "red" if sev in ("BLOCKER", "HIGH") else ("yellow" if sev == "MEDIUM" else "dim")
            )
            f_table.add_row(
                item.get("finding_id", ""),
                f"[{style}]{sev}[/{style}]",
                item.get("code", ""),
                item.get("title", ""),
            )
        console.print(f_table)
        return

    # Action is 'run' or 'refresh'
    console.print("[bold cyan]Agentic OS — Project Continuation Audit (§PCA)[/bold cyan]")
    snapshot = create_project_snapshot(root)
    arch, findings = run_static_discovery(root, snapshot)

    baseline: ProjectBaseline | None = None
    if dynamic:
        console.print("[dim]Executing dynamic baseline diagnostics inside sandbox...[/dim]")
        checks: list[BaselineCheckResult] = []

        if (root / "tests").is_dir():
            t0 = time.time()
            res = subprocess.run(
                ["uv", "run", "pytest", "-q"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            duration = int((time.time() - t0) * 1000)
            status = "PASS" if res.returncode == 0 else "FAIL"
            checks.append(
                BaselineCheckResult(
                    check_type=DiagnosticType.UNIT_TEST,
                    command="uv run pytest -q",
                    exit_code=res.returncode,
                    duration_ms=duration,
                    status=status,
                    stdout_hash=str(hash(res.stdout)),
                    stderr_hash=str(hash(res.stderr)),
                )
            )

        baseline = ProjectBaseline(snapshot_id=snapshot.snapshot_id, checks=checks)

    report = synthesize_continuation_report(
        snapshot=snapshot,
        architecture=arch,
        findings=findings,
        baseline=baseline,
    )

    pack_dir = store.save_pack(
        project_id=project_id,
        snapshot=snapshot,
        architecture=arch,
        findings=findings,
        report=report,
        baseline=baseline,
    )

    # Output executive layout matching §36
    summary_table = Table(title=f"PCA Snapshot: {snapshot.repository}")
    summary_table.add_column("Property", style="cyan")
    summary_table.add_column("Value", style="green")

    commit_str = (
        snapshot.base_commit[:7] if len(snapshot.base_commit) >= 7 else snapshot.base_commit
    )
    summary_table.add_row("Base Commit", commit_str)
    summary_table.add_row("Branch", snapshot.branch)
    wt_clean = snapshot.working_tree.clean
    summary_table.add_row(
        "Working Tree",
        "[green]CLEAN[/green]" if wt_clean else "[yellow]DIRTY[/yellow]",
    )
    summary_table.add_row("Total Files", str(len(snapshot.tracked_files)))
    langs = ", ".join(f"{k} ({int(v * 100)}%)" for k, v in arch.languages.items())
    summary_table.add_row("Stack", langs or "unspecified")
    summary_table.add_row("Findings Count", str(len(findings)))
    summary_table.add_row("Context Digest", (report.context_digest or "")[:16] + "...")
    console.print(summary_table)

    if findings:
        console.print("\n[bold]Key Findings:[/bold]")
        for f in findings[:5]:
            color = (
                "red" if f.severity in (FindingSeverity.BLOCKER, FindingSeverity.HIGH) else "yellow"
            )
            console.print(
                f"  [{color}]{f.severity.value:<7}[/{color}] "
                f"{f.finding_id} {f.code.value} - {f.title}"
            )

    out_file = pack_dir / "CONTINUATION_CONTEXT.md"
    console.print(f"\n[bold green]✓ Continuation pack generated:[/bold green] {out_file}\n")


def cmd_run(
    prompt: str,
    repo_path: str = ".",
    auto_approve: bool = False,
    model_id: str = "mock",
) -> None:
    root = Path(repo_path).resolve()
    console.print("[bold cyan]myagentos — Executing Autonomous Pipeline (§8)[/bold cyan]")
    console.print(f"Target Repository: [green]{root}[/green]")
    console.print(f"Task Prompt: [magenta]{prompt}[/magenta]\n")

    config = PipelineConfig(
        repo_root=root,
        model_id=model_id,
        auto_approve=auto_approve,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(config=config)
    result = orchestrator.run(prompt)

    table = Table(title=f"Pipeline Execution Summary: {result.job_id}")
    table.add_column("Stage / Property", style="cyan")
    table.add_column("Result", style="green" if result.success else "red")

    table.add_row("Status", "SUCCESS" if result.success else "FAILED")
    table.add_row("Final FSM State", result.final_state.value)
    table.add_row("Routing Intent", result.intent)
    if result.plan:
        targets = ", ".join(result.plan.all_targeted_paths()) or "none"
        table.add_row("Plan Targets", targets)
        table.add_row("Preliminary Risk", result.plan.preliminary_risk.value)
    if result.patch_set:
        table.add_row("Modified Files", str(result.patch_set.total_files))
        table.add_row("Diff Lines", str(result.patch_set.total_diff_lines))
    table.add_row("Audit Events", str(result.audit_events_count))
    table.add_row(
        "Cryptographic Hash Chain",
        "INTACT ✓" if result.hash_chain_intact else "CORRUPTED ✗",
    )
    table.add_row("Duration", f"{result.duration_seconds:.2f}s")
    table.add_row("Summary", result.summary)

    console.print(table)
    if not result.success:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="myagentos", description="Agentic OS CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # run command (§8 E2E execution)
    p_run = subparsers.add_parser("run", help="Run autonomous code task end-to-end")
    p_run.add_argument("prompt", help="Task prompt or goal description")
    p_run.add_argument("--repo", default=".", help="Repository root path")
    p_run.add_argument("--auto-approve", action="store_true", help="Auto-approve plan and diff")
    p_run.add_argument("--model", default="mock", help="Model ID for Planner and Worker")

    # route command
    p_route = subparsers.add_parser("route", help="Route prompt locally")
    p_route.add_argument("prompt", help="Prompt text or slash command")

    # status command
    p_status = subparsers.add_parser("status", help="Get status of a job")
    p_status.add_argument("job_id", help="Job ID")

    # verify command
    p_verify = subparsers.add_parser("verify", help="Verify event log hash chain")
    p_verify.add_argument("job_id", help="Job ID")

    # benchmark command
    subparsers.add_parser("benchmark", help="Run benchmark suite")

    # continue command (§35 of PCA spec)
    p_continue = subparsers.add_parser("continue", help="Run Project Continuation Audit")
    p_continue.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=["run", "report", "findings", "refresh"],
        help="Action to execute",
    )
    p_continue.add_argument(
        "--dynamic",
        action="store_true",
        help="Run dynamic diagnostics in sandbox",
    )
    p_continue.add_argument("--repo", default=".", help="Repository root path")

    args = parser.parse_args()

    if args.subcommand == "run":
        cmd_run(
            prompt=args.prompt,
            repo_path=args.repo,
            auto_approve=args.auto_approve,
            model_id=args.model,
        )
    elif args.subcommand == "route":
        cmd_route(args.prompt)
    elif args.subcommand == "status":
        cmd_status(args.job_id)
    elif args.subcommand == "verify":
        cmd_verify(args.job_id)
    elif args.subcommand == "benchmark":
        cmd_benchmark()
    elif args.subcommand == "continue":
        cmd_continue(action=args.action, repo_path=args.repo, dynamic=args.dynamic)


if __name__ == "__main__":
    main()
