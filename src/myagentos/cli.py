"""Command line interface for myagentos."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from myagentos.benchmark import BenchmarkHarness, BenchmarkTask
from myagentos.categorization import ProjectCategorizationService
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.core.store.state_projector import StateProjector
from myagentos.pipeline import PipelineConfig, PipelineOrchestrator
from myagentos.projects import ProjectFilter, ProjectManagerService
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


def cmd_benchmark(
    suite: str = "smoke",
    output_path: str | None = None,
    model_id: str = "mock",
    harness_only: bool = False,
) -> None:
    if harness_only:
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
                expected_intent=RoutingIntent.PLANNED_CODE,
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
        return

    from myagentos.benchmark.runner import BenchmarkRunner
    from myagentos.gateway.client import ModelGateway

    gateway = ModelGateway()
    runner = BenchmarkRunner(gateway=gateway, model_id=model_id)

    out_file = Path(output_path) if output_path else None
    console.print(
        f"[bold cyan]Running myagentos Benchmark (§26, §28) — Suite: '{suite}'[/bold cyan]"
    )

    report = runner.run_suite(suite_name=suite, output_file=out_file)

    # 1. Summary Metrics Comparison
    summary_table = Table(title=f"Benchmark Summary Metrics — Suite '{suite}' (§26.2)")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Baseline", style="yellow")
    summary_table.add_column("myAgentOS", style="green")
    summary_table.add_column("Advantage / Defense", style="bold blue")

    summary_table.add_row(
        "Task Success Rate",
        f"{report.baseline_success_rate:.1f}%",
        f"{report.myagentos_success_rate:.1f}%",
        f"{report.myagentos_success_rate - report.baseline_success_rate:+.1f}%",
    )
    summary_table.add_row(
        "False-Direct Defense",
        "0.0% (Unchecked)",
        f"{100.0 - report.false_direct_rate:.1f}%",
        "Deterministic Escalation",
    )
    summary_table.add_row(
        "Policy Defense Rate",
        "0.0% (No limits)",
        f"{report.policy_violation_defense_rate:.1f}%",
        "Strict Token Ceilings",
    )
    summary_table.add_row(
        "Protected Test Defense",
        "0.0% (Tamperable)",
        f"{report.protected_tampering_defense_rate:.1f}%",
        "Cryptographic Guard",
    )
    summary_table.add_row(
        "Avg Latency",
        f"{report.avg_latency_baseline_ms:.1f} ms",
        f"{report.avg_latency_myagentos_ms:.1f} ms",
        f"{report.avg_latency_myagentos_ms - report.avg_latency_baseline_ms:+.1f} ms",
    )
    summary_table.add_row(
        "Total Tokens",
        f"{report.total_tokens_baseline:,}",
        f"{report.total_tokens_myagentos:,}",
        f"{report.total_tokens_myagentos - report.total_tokens_baseline:+,}",
    )
    summary_table.add_row(
        "Estimated Cost",
        f"${report.total_cost_baseline_usd:.4f}",
        f"${report.total_cost_myagentos_usd:.4f}",
        f"${report.total_cost_myagentos_usd - report.total_cost_baseline_usd:+.4f}",
    )
    summary_table.add_row(
        "Hash Chain Integrity",
        "N/A",
        f"{report.hash_chain_integrity_rate:.1f}%",
        "100% Tamper-Evident",
    )
    console.print(summary_table)

    # 2. Detailed Task Breakdown Table
    detail_table = Table(title="Task-by-Task Comparative Breakdown (§26.1)")
    detail_table.add_column("Task ID", style="cyan")
    detail_table.add_column("Category", style="magenta")
    detail_table.add_column("Baseline State", style="yellow")
    detail_table.add_column("myAgentOS State", style="green")
    detail_table.add_column("Defense Triggered", style="blue")
    detail_table.add_column("Chain", style="bold green")

    for res in report.results:
        b = res.baseline
        m = res.myagentos
        defense = (
            "Protected Test Defended"
            if m.protected_tampering_blocked
            else ("Policy Violation Blocked" if m.policy_violation_caught else "Normal Completion")
        )
        detail_table.add_row(
            res.task.task_id,
            res.task.category.value,
            b.final_state,
            m.final_state,
            defense,
            "VALID" if m.hash_chain_intact else "CORRUPTED",
        )

    console.print(detail_table)
    if output_path:
        console.print(f"[bold green]Full benchmark report saved to {output_path}[/bold green]")


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
    snaps: list[Path] = []

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
        if not pdir.is_dir():
            console.print(
                f"[yellow]No findings found for '{project_id}'."
                " Run `myagentos continue` first.[/yellow]"
            )
            return

        snaps = sorted(
            [d for d in pdir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
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
    connection_id: str | None = None,
) -> None:
    root = Path(repo_path).resolve()
    console.print("[bold cyan]myagentos — Executing Autonomous Pipeline (§8)[/bold cyan]")
    console.print(f"Target Repository: [green]{root}[/green]")
    console.print(f"Task Prompt: [magenta]{prompt}[/magenta]")
    if connection_id:
        console.print(f"Plan Connection: [yellow]{connection_id}[/yellow]")
    console.print()

    plan_cb = None
    diff_cb = None
    if not auto_approve and sys.stdin.isatty():
        from rich.prompt import Confirm

        def cli_plan_approval(plan_id: str, plan_spec: Any) -> bool:
            console.print(f"\n[bold yellow]⚠️  Plan Approval Requested for {plan_id}[/bold yellow]")
            targets = ", ".join(plan_spec.all_targeted_paths()) or "none"
            console.print(f"Targeted files: [cyan]{targets}[/cyan]")
            return Confirm.ask("Do you approve this execution plan?", default=False)

        def cli_diff_approval(job_id: str, patch_set: Any) -> bool:
            console.print(f"\n[bold yellow]⚠️  Diff Approval Requested for {job_id}[/bold yellow]")
            console.print(f"Files modified: [cyan]{patch_set.total_files}[/cyan]")
            for f in patch_set.files:
                console.print(f"  [{f.operation.value}] {f.path}")
            return Confirm.ask(
                "Do you approve merging these changes into the repository?", default=False
            )

        plan_cb = cli_plan_approval
        diff_cb = cli_diff_approval

    config = PipelineConfig(
        repo_root=root,
        model_id=model_id,
        auto_approve=auto_approve,
        use_worktree=True,
        approval_callback=plan_cb,
        diff_approval_callback=diff_cb,
        connection_id=connection_id,
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


def cmd_categorize(repo_path: str = ".", force: bool = False, json_output: bool = False) -> None:
    root = Path(repo_path).resolve()
    service = ProjectCategorizationService()
    profile = service.scan_project(root, force=force)

    if json_output:
        console.print(profile.model_dump_json(indent=2))
        return

    table = Table(title=f"Project Profile: {profile.repository} ({profile.status.value.upper()})")
    table.add_column("Property", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    tags_str = " ".join(f"[{t.label}]" for t in profile.visible_tags)
    table.add_row("Visible Tags (UX)", f"[bold magenta]{tags_str}[/bold magenta]")
    table.add_row("Languages", ", ".join(profile.stack.languages) or "N/A")
    table.add_row("Frameworks", ", ".join(profile.stack.frameworks) or "none")
    table.add_row("Databases", ", ".join(profile.stack.databases) or "none")
    table.add_row("Application Type", ", ".join(profile.architecture.application_type) or "N/A")
    table.add_row("Containers", ", ".join(profile.infrastructure.containers) or "none")
    table.add_row("CI/CD", ", ".join(profile.infrastructure.ci_cd) or "none")
    table.add_row(
        "Quality",
        f"Tests: {', '.join(profile.quality.test_frameworks) or 'none'} | "
        f"Typing: {'✓' if profile.quality.typechecking else '✗'} | "
        f"Linting: {'✓' if profile.quality.linting else '✗'}",
    )
    table.add_row("Scan Hash", profile.scan_hash[:16] + "...")

    console.print(table)


def cmd_project(
    action: str = "list",
    target: str | None = None,
    secondary: str | None = None,
    name: str | None = None,
    repo_path: str = ".",
    tag: str | None = None,
    search: str | None = None,
    json_output: bool = False,
    force: bool = False,
    confirm: bool = False,
) -> None:
    mgr = ProjectManagerService()

    if action == "list":
        projects = mgr.list_projects(filter_criteria=ProjectFilter(query=search, tag=tag))
        if json_output:
            console.print(json.dumps([p.model_dump(mode="json") for p in projects], indent=2))
            return

        table = Table(title=f"Agentic OS — Active Projects ({len(projects)})")
        table.add_column("Project", style="bold cyan")
        table.add_column("State", style="green")
        table.add_column("Visible Tags", style="magenta")
        table.add_column("Path", style="dim")
        table.add_column("Git", style="yellow")

        for p in projects:
            tags = " ".join(f"[{t.label}]" for t in p.visible_tags)
            git_info = f"{p.branch or 'N/A'}"
            if p.commit_short:
                git_info += f" ({p.commit_short})"
            table.add_row(p.name, p.state.value.upper(), tags, p.path, git_info)

        console.print(table)
        return

    if action == "add":
        target_path = Path(target or repo_path).resolve()
        try:
            proj = mgr.add_project(target_path, name=name)
            console.print(
                f"[bold green]✓ Project added:[/bold green] {proj.name} ({proj.project_id})"
            )
            tags = " ".join(f"[{t.label}]" for t in proj.visible_tags)
            console.print(f"  Visible tags: [magenta]{tags}[/magenta]")
            console.print(f"  Mya namespace: [dim]{proj.mya_namespace_id}[/dim]")
        except Exception as exc:
            console.print(f"[bold red]✗ Failed adding project:[/bold red] {exc}")
            sys.exit(1)
        return

    if action in ("init", "reset"):
        target_path = Path(target or repo_path).resolve()
        is_reset = action == "reset" or force
        if is_reset:
            res = mgr.reset_project_mya_environment(target_path, project_name=name)
        else:
            res = mgr.ensure_project_mya_environment(target_path, project_name=name)

        if res.get("status") == "error":
            console.print(
                f"[bold red]✗ Failed to initialize project:[/bold red] {res.get('reason')}"
            )
            sys.exit(1)

        action_desc = "reinicializada" if is_reset else "verificada"
        console.print(f"[bold green]✓ Estructura de Mya {action_desc}:[/bold green] {target_path}")
        if res.get("backup"):
            console.print(f"  [yellow]Backup de MYA.md:[/yellow] {res['backup']}")
        if res.get("created"):
            for it in res["created"]:
                console.print(f"  [green]+[/green] {it}")
        else:
            console.print("  [cyan]Todos los ficheros y directorios ya existían.[/cyan]")
        return

    if action == "new":
        if not target:
            console.print(
                "[bold red]✗ Project name is required for 'project new <name>'[/bold red]"
            )
            sys.exit(1)
        new_dir = Path(repo_path) / target if repo_path != "." else Path.cwd() / target
        try:
            proj = mgr.create_project(name=target, path=new_dir)
            console.print(
                f"[bold green]✓ Project created:[/bold green] {proj.name} ({proj.project_id})"
            )
            console.print(f"  Location: {proj.path}")
        except Exception as exc:
            console.print(f"[bold red]✗ Failed creating project:[/bold red] {exc}")
            sys.exit(1)
        return

    if action == "clone":
        if not target or not secondary:
            console.print("[bold red]✗ URL and destination required for 'project clone'[/bold red]")
            sys.exit(1)
        try:
            proj = mgr.clone_repository(url=target, destination=secondary, name=name)
            console.print(
                f"[bold green]✓ Repository cloned and registered:[/bold green] {proj.name} "
                f"({proj.project_id})"
            )
        except Exception as exc:
            console.print(f"[bold red]✗ Failed cloning repository:[/bold red] {exc}")
            sys.exit(1)
        return

    if action == "trash":
        sub = target or "list"
        if sub == "list":
            trash_items = mgr.list_trash()
            if json_output:
                dumped = [p.model_dump(mode="json") for p in trash_items]
                console.print(json.dumps(dumped, indent=2))
                return
            table = Table(title=f"Agentic OS — Project Trash ({len(trash_items)})")
            table.add_column("Project", style="bold red")
            table.add_column("Tags", style="magenta")
            table.add_column("Location", style="dim")
            table.add_column("Trashed At", style="yellow")

            for p in trash_items:
                tags = " ".join(f"[{t.label}]" for t in p.visible_tags)
                trashed_time = p.trashed_at.strftime("%Y-%m-%d %H:%M") if p.trashed_at else "N/A"
                table.add_row(p.name, tags, p.path, trashed_time)

            console.print(table)
            return

        proj_id = secondary or target
        if not proj_id:
            console.print("[bold red]✗ Project ID or name required[/bold red]")
            sys.exit(1)

        target_proj = mgr.get_project(proj_id)
        if not target_proj:
            console.print(f"[bold red]✗ Project not found: {proj_id}[/bold red]")
            sys.exit(1)

        if sub == "move":
            updated = mgr.move_to_trash(target_proj.project_id)
            console.print(
                f"[bold yellow]✓ Moved '{updated.name}' to Trash.[/bold yellow]\n"
                f"  [dim]Repository files at '{updated.path}' remain untouched on disk.[/dim]"
            )
            return

        if sub == "restore":
            restored = mgr.restore_project(target_proj.project_id)
            console.print(f"[bold green]✓ Restored '{restored.name}' to ACTIVE.[/bold green]")
            return

        if sub == "purge":
            if not confirm:
                console.print(
                    f"[bold red]Permanently delete registration for '{target_proj.name}'?"
                    "[/bold red]\n"
                    "This removes project registration and Mya memory association.\n"
                    "The repository code on disk will NOT be deleted.\n"
                    "Pass [bold]--confirm[/bold] to proceed."
                )
                sys.exit(1)
            mgr.delete_permanently(target_proj.project_id, confirm=True)
            console.print(
                f"[bold red]✓ Permanently deleted registration for '{target_proj.name}'."
                "[/bold red]\n"
                f"  [dim]Repository files at '{target_proj.path}' were NOT deleted.[/dim]"
            )
            return

    # Fallback to profile / tags / categorize
    if action in ("categorize", "profile", "tags"):
        cat_service = ProjectCategorizationService()
        root = Path(repo_path).resolve()
        if action == "categorize":
            cmd_categorize(repo_path=repo_path, force=force, json_output=json_output)
            return
        profile = cat_service.scan_project(root, project_id=target, force=force)
        if json_output:
            console.print(profile.model_dump_json(indent=2))
            return
        if action == "tags":
            table = Table(title=f"Visible Tags: {profile.repository}")
            table.add_column("Tag", style="bold magenta")
            table.add_column("Category", style="cyan")
            table.add_column("Confidence", style="green")
            table.add_column("Source", style="yellow")
            table.add_column("Pinned", style="blue")
            for t in profile.visible_tags:
                table.add_row(
                    t.label,
                    t.category.value,
                    f"{t.confidence:.2f}",
                    t.source.value,
                    "✓" if t.pinned else "",
                )
            console.print(table)
            return
        cmd_categorize(repo_path=repo_path, force=force, json_output=json_output)


def cmd_mya(
    command: str | None = None,
    argument: str = "",
    repo_path: str = ".",
) -> None:
    """Executes a single Mya command or launches the interactive terminal (§24)."""
    if command is None:
        from myagentos.ui.app import run as run_mya

        run_mya(repo_path=repo_path)
        return

    from myagentos.gateway.client import ModelGateway
    from myagentos.gateway.mock_adapter import MockProviderAdapter
    from myagentos.mya.commands import CommandHandlerService, ObservabilityService
    from myagentos.ui.session import create_session

    cmd = command.strip().lower()
    if not cmd.startswith("/"):
        cmd = f"/{cmd}"

    session = create_session(Path(repo_path).resolve())
    obs = ObservabilityService()
    handlers = CommandHandlerService()

    if cmd == "/info":
        console.print(obs.render_info(session))
    elif cmd in ("/connect", "/account"):
        parts = argument.strip().split(maxsplit=1)
        subaction = parts[0].lower() if parts else "status"
        sub_arg = parts[1] if len(parts) > 1 else None
        if subaction in ("chatgpt", "openai"):
            cmd_model(action="connect", target="openai")
        elif subaction in ("claude", "anthropic"):
            cmd_model(action="connect", target="claude")
        elif subaction in ("disconnect", "remove"):
            cmd_model(action="disconnect", target=sub_arg)
        elif subaction == "list":
            cmd_model(action="list")
        else:
            cmd_model(action="status", target=sub_arg)
    elif cmd == "/telemetry":
        console.print(obs.render_telemetry(session.current_job_id))
    elif cmd == "/monitor":
        console.print(obs.render_monitor(session.current_job_id, session))
    elif cmd == "/fast":
        _, msg = handlers.handle_fast(argument)
        console.print(msg)
    elif cmd == "/sci_mode":
        console.print(handlers.handle_sci_mode(argument))
    elif cmd == "/deep_research":
        console.print(handlers.handle_deep_research(argument))
    elif cmd == "/optimize":
        console.print(handlers.handle_optimize(argument))
    elif cmd == "/decision":
        console.print(handlers.handle_decision(argument))
    elif cmd == "/cloud":
        console.print(handlers.handle_cloud(argument))
    elif cmd == "/security":
        console.print(handlers.handle_security(argument))
    elif cmd == "/theme":
        from myagentos.ui.theme.themes import ThemeRegistry

        reg = ThemeRegistry.get_instance()
        if not argument:
            avail = ", ".join(t.name for t in reg.list_themes())
            console.print(f"[bold]Active Theme:[/bold] {reg.active_theme.name}\nAvailable: {avail}")
        else:
            try:
                th = reg.set_active_theme(argument)
                console.print(f"[bold green]✓ Switched theme to '{th.name}'[/bold green]")
            except ValueError as err:
                console.print(f"[bold red]Error:[/bold red] {err}")
    elif cmd == "/motion":
        from myagentos.ui.visual.motion import MotionController

        ctrl = MotionController.get_instance()
        if not argument:
            console.print(f"[bold]Motion Mode:[/bold] {ctrl.mode.value}")
        else:
            try:
                m = ctrl.set_mode(argument)
                console.print(f"[bold green]✓ Motion mode set to '{m.value}'[/bold green]")
            except ValueError as err:
                console.print(f"[bold red]Error:[/bold red] {err}")
    elif cmd == "/avatar":
        from myagentos.mya.presentation import MyaRenderState, get_mya_renderer

        valid = ["dot", "glyph", "ascii", "minimal"]
        if not argument:
            console.print(f"[bold]Avatar Modes:[/bold] {', '.join(valid)}")
        elif argument.lower() in valid:
            rend = get_mya_renderer(argument)
            rs = MyaRenderState(status="IDLE", label="Ready", avatar_mode=argument)
            console.print(f"[bold green]✓ Avatar mode '{argument}':[/bold green]\n")
            console.print(rend.render_avatar(rs))
        else:
            console.print(
                f"[bold red]Error:[/bold red] Unknown mode '{argument}'. Valid: {', '.join(valid)}"
            )
    elif cmd in ("/init", "/reset"):
        from myagentos.projects.service import ProjectManagerService

        root = Path(repo_path).resolve()
        is_reset = cmd == "/reset" or argument.strip().lower() in (
            "reset",
            "force",
            "--reset",
            "--force",
        )
        if is_reset:
            res = ProjectManagerService.reset_project_mya_environment(root)
        else:
            res = ProjectManagerService.ensure_project_mya_environment(root)

        if res.get("status") == "error":
            console.print(f"[bold red]Error:[/bold red] {res.get('reason')}")
        else:
            action_desc = "reinicializada" if is_reset else "verificada"
            console.print(f"[bold green]✓ Estructura de Mya {action_desc} en {root}[/bold green]")
            if res.get("backup"):
                console.print(f"  [yellow]Backup de MYA.md:[/yellow] {res['backup']}")
            if res.get("created"):
                for it in res["created"]:
                    console.print(f"  [green]+[/green] {it}")
            else:
                console.print("  [cyan]Todos los ficheros y directorios ya existían.[/cyan]")
    else:
        from myagentos.mya.agent import MyaAgent

        gw = ModelGateway()
        if "mock" not in gw.adapters:
            gw.register_adapter("mock", MockProviderAdapter())
        agent = MyaAgent(gateway=gw, model_id="mock")
        resp = agent.converse(f"{command} {argument}".strip(), session=session)
        console.print(resp)


def cmd_setup(
    name: str | None = None,
    theme: str | None = None,
    mya_home: str | None = None,
    non_interactive: bool = False,
    force: bool = False,
) -> None:
    """Non-interactive or CLI-driven first-run setup (§24)."""
    import getpass
    from datetime import datetime

    from myagentos.config.loader import save_config
    from myagentos.config.paths import DEFAULT_MYA_HOME
    from myagentos.setup.detector import is_setup_complete
    from myagentos.setup.initializer import initialize_mya_home
    from myagentos.setup.models import (
        MyaHomeConfig,
        SetupConfig,
        SetupMeta,
        UIConfig,
        UserConfig,
    )
    from myagentos.setup.validator import validate_mya_home

    home_path = Path(mya_home).expanduser().resolve() if mya_home else DEFAULT_MYA_HOME.resolve()

    if not force and is_setup_complete(home_path):
        console.print(
            f"[yellow]Mya setup is already completed at {home_path}.\n"
            f"Use --force to re-initialize.[/yellow]"
        )
        return

    # Validate destination
    val_res = validate_mya_home(home_path)
    if not val_res.valid:
        console.print(f"[red]Error:[/red] {val_res.error}")
        sys.exit(1)

    target_home = val_res.resolved_path or home_path

    # Determine user and theme
    if not name:
        try:
            name = getpass.getuser().capitalize()
        except Exception:
            name = "Developer"

    resolved_theme = (theme or "default").strip().lower()
    from myagentos.ui.theme.themes import ThemeRegistry

    reg = ThemeRegistry.get_instance()
    if resolved_theme not in reg._themes:
        available = ", ".join(sorted(reg._themes.keys()))
        console.print(
            f"[red]Error:[/red] Theme '{resolved_theme}' is invalid. Available: {available}"
        )
        sys.exit(1)

    # Initialize Mya Home directory structure
    try:
        initialize_mya_home(target_home)
    except Exception as exc:
        console.print(f"[red]Error creating Mya Home directories:[/red] {exc}")
        sys.exit(1)

    # Build and save configuration
    config = SetupConfig(
        schema_version=1,
        setup=SetupMeta(
            completed=True,
            completed_at=datetime.now(UTC).isoformat(),
            version=1,
        ),
        user=UserConfig(display_name=name),
        ui=UIConfig(theme=resolved_theme, motion="full"),
        mya=MyaHomeConfig(home=str(target_home)),
    )

    try:
        save_config(config, mya_home=target_home)
    except Exception as exc:
        console.print(f"[red]Error writing configuration:[/red] {exc}")
        sys.exit(1)

    console.print(
        f"[bold green]✓ Mya Home initialized successfully.[/bold green]\n"
        f"  [cyan]Home:[/]    {target_home}\n"
        f"  [cyan]User:[/]    {name}\n"
        f"  [cyan]Theme:[/]   {resolved_theme}"
    )


def cmd_model(
    action: str,
    target: str | None = None,
    sub_target: str | None = None,
    auth: str | None = None,
    no_browser: bool = False,
    refresh: bool = False,
    json_output: bool = False,
) -> None:
    """Manage model subscription plan connections (§AO-MODEL-PLAN-CONNECT-01)."""
    from myagentos.gateway.chatgpt_plan_adapter import ChatGPTPlanAdapter
    from myagentos.gateway.claude_code_adapter import ClaudeCodeAdapter
    from myagentos.gateway.client import ModelGateway
    from myagentos.gateway.credentials import CredentialStatus
    from myagentos.gateway.oauth_openai import OpenAIOAuthClient
    from myagentos.gateway.plan_connection import (
        ConnectionAuthKind,
        ConnectionPlatform,
        ConnectionServiceStatus,
        PlanConnectionProfile,
    )

    gateway = ModelGateway()

    # Normalization:
    # "myagentos model connection list" -> action="list", target=None
    # "myagentos model connection status <id>" -> action="status", target=<id>
    if action == "connection":
        sub_act = (target or "list").lower().strip()
        if sub_act in ("list", "ls"):
            action = "list"
            target = None
        elif sub_act in ("status", "info"):
            action = "status"
            target = sub_target
        else:
            console.print(
                f"[red]Unknown connection sub-action '{sub_act}'. Use 'list' or 'status'.[/red]"
            )
            sys.exit(1)

    if action == "connect":
        provider = (target or "").lower().strip()
        if not provider:
            console.print("[red]Missing provider for connect. Specify 'openai' or 'claude'.[/red]")
            sys.exit(1)

        if provider in ("openai", "chatgpt"):
            auth_method = (auth or "oauth").lower().strip()
            if auth_method != "oauth":
                console.print(
                    f"[red]Unsupported auth method '{auth_method}' for OpenAI. "
                    "Use '--auth oauth'.[/red]"
                )
                sys.exit(1)

            console.print("[cyan]Initiating PKCE OAuth flow for ChatGPT Plus/Pro...[/cyan]")
            oauth_client = OpenAIOAuthClient(store=gateway.credential_store)

            def _on_url(url: str) -> None:
                console.print(f"[bold green]Authorization URL:[/bold green]\n{url}\n")
                if no_browser:
                    console.print(
                        "[yellow]Please open the URL above in your browser to login.[/yellow]"
                    )

            try:
                profile = oauth_client.connect_interactive(
                    open_browser=not no_browser,
                    on_url_ready=_on_url if no_browser else None,
                )
            except Exception as e:
                console.print(f"[red]OAuth authentication failed:[/red] {e}")
                sys.exit(1)

            # Discover models via adapter
            try:
                chatgpt_adapter = ChatGPTPlanAdapter(
                    connection_profile=profile, store=gateway.credential_store
                )
                models = chatgpt_adapter.discover_models()
                model_ids = [m.model_id for m in models]
            except Exception:
                model_ids = ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini"]

            profile = profile.model_copy(
                update={"models": model_ids, "status": ConnectionServiceStatus.READY}
            )
            gateway.credential_store.save_profile(profile)
            gateway.load_persisted_connections()

            if json_output:
                console.print(json.dumps(profile.model_dump(mode="json"), indent=2))
                return

            table = Table(title="ChatGPT Plan Connection Established")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Connection ID", profile.connection_id)
            table.add_row("Platform", profile.platform.value)
            table.add_row("Auth Method", profile.auth_kind.value)
            table.add_row("Account", profile.account_label)
            table.add_row("Status", profile.status.value)
            table.add_row("Models", ", ".join(profile.models) if profile.models else "none")
            console.print(table)
            console.print(
                f"\n[green]✓ Connected successfully.[/green] "
                f"Use with: [bold]myagentos run --connection {profile.connection_id}[/bold]"
            )

        elif provider in ("claude", "anthropic"):
            auth_method = (auth or "cli").lower().strip()
            if auth_method != "cli":
                console.print(
                    f"[red]Unsupported auth method '{auth_method}' for Claude. "
                    "Use '--auth cli'.[/red]"
                )
                sys.exit(1)

            conn_id = sub_target or "conn_claude_cli"
            profile = PlanConnectionProfile(
                connection_id=conn_id,
                provider="anthropic",
                platform=ConnectionPlatform.CLAUDE,
                auth_kind=ConnectionAuthKind.CLI_DELEGATED,
                account_label="Claude CLI Delegated",
                status=ConnectionServiceStatus.READY,
                tier="pro",
                last_validated_at=datetime.now(UTC),
            )
            claude_adapter = ClaudeCodeAdapter(connection_profile=profile)
            status, err_msg, identity = claude_adapter.validate_credential()

            if status == CredentialStatus.PROVIDER_UNAVAILABLE:
                console.print("[red]Claude Code CLI is not installed.[/red]")
                console.print(f"Details: {err_msg}")
                console.print(
                    "Please install Claude Code CLI via: npm install -g @anthropic-ai/claude-code"
                )
                sys.exit(1)

            if status != CredentialStatus.VALID:
                console.print(
                    f"[red]Claude Code CLI is not authenticated with claude.ai:[/red] {err_msg}"
                )
                console.print(
                    "Please run [bold]claude[/bold] or [bold]claude login[/bold] "
                    "to log in with your Claude Pro/Max account."
                )
                sys.exit(1)

            account_label = identity.principal_name if identity else "Claude Pro/Max Account"
            disc_models = claude_adapter.discover_models()
            model_ids = [m.model_id for m in disc_models]

            profile = profile.model_copy(
                update={"account_label": account_label, "models": model_ids}
            )
            gateway.credential_store.save_profile(profile)
            gateway.load_persisted_connections()

            if json_output:
                console.print(json.dumps(profile.model_dump(mode="json"), indent=2))
                return

            table = Table(title="Claude Code Plan Connection Established")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Connection ID", profile.connection_id)
            table.add_row("Platform", profile.platform.value)
            table.add_row("Auth Method", profile.auth_kind.value)
            table.add_row("Account", profile.account_label)
            table.add_row("Status", profile.status.value)
            table.add_row("Models", ", ".join(profile.models) if profile.models else "none")
            console.print(table)
            console.print(
                f"\n[green]✓ Connected successfully.[/green] "
                f"Use with: [bold]myagentos run --connection {profile.connection_id}[/bold]"
            )

        else:
            console.print(
                f"[red]Unknown provider '{provider}'. Supported: 'openai', 'claude'.[/red]"
            )
            sys.exit(1)

    elif action in ("list", "ls"):
        profiles = gateway.list_plan_connections()
        if not profiles:
            profiles = gateway.credential_store.list_profiles()

        if json_output:
            console.print(json.dumps([p.model_dump(mode="json") for p in profiles], indent=2))
            return

        if not profiles:
            console.print("[yellow]No active model plan connections found.[/yellow]")
            console.print(
                "To connect a subscription, run: [bold]myagentos model connect openai|claude[/bold]"
            )
            return

        table = Table(title="Active Model Plan Connections")
        table.add_column("Connection ID", style="cyan")
        table.add_column("Platform", style="magenta")
        table.add_column("Auth Kind", style="blue")
        table.add_column("Tier", style="yellow")
        table.add_column("Status", style="green")
        table.add_column("Account", style="white")
        table.add_column("Models", style="dim")

        for p in profiles:
            st = p.status
            status_style = (
                "green"
                if st == ConnectionServiceStatus.READY
                else ("red" if st == ConnectionServiceStatus.QUOTA_EXHAUSTED else "yellow")
            )
            table.add_row(
                p.connection_id,
                p.platform.value,
                p.auth_kind.value,
                p.tier,
                f"[{status_style}]{st.value}[/{status_style}]",
                p.account_label,
                ", ".join(p.models[:3]) + ("..." if len(p.models) > 3 else ""),
            )
        console.print(table)

    elif action in ("status", "info"):
        if not target:
            console.print("[red]Missing connection ID for status check.[/red]")
            sys.exit(1)
        conn_id = target

        found_profile = gateway.get_plan_connection(
            conn_id
        ) or gateway.credential_store.get_profile(conn_id)
        if not found_profile:
            console.print(f"[red]Connection '{conn_id}' not found.[/red]")
            sys.exit(1)

        active_profile = found_profile
        if refresh:
            if active_profile.platform in (
                ConnectionPlatform.CHATGPT_PLAN,
                ConnectionPlatform.OPENAI,
            ):
                oauth_client = OpenAIOAuthClient(store=gateway.credential_store)
                try:
                    oauth_client.refresh_access_token(conn_id)
                    active_profile = active_profile.model_copy(
                        update={
                            "status": ConnectionServiceStatus.READY,
                            "last_validated_at": datetime.now(UTC),
                            "error_message": None,
                        }
                    )
                    gateway.credential_store.save_profile(active_profile)
                    gateway.load_persisted_connections()
                except Exception as e:
                    active_profile = active_profile.model_copy(
                        update={
                            "status": ConnectionServiceStatus.DEGRADED,
                            "error_message": str(e),
                        }
                    )
                    gateway.credential_store.save_profile(active_profile)
            elif active_profile.platform in (
                ConnectionPlatform.CLAUDE,
                ConnectionPlatform.CLAUDE_CODE,
            ):
                status_claude_adapter = ClaudeCodeAdapter(connection_profile=active_profile)
                c_status, err, _ = status_claude_adapter.validate_credential()
                new_status = (
                    ConnectionServiceStatus.READY
                    if c_status == CredentialStatus.VALID
                    else ConnectionServiceStatus.DEGRADED
                )
                active_profile = active_profile.model_copy(
                    update={
                        "status": new_status,
                        "error_message": err,
                        "last_validated_at": datetime.now(UTC),
                    }
                )
                gateway.credential_store.save_profile(active_profile)

        if json_output:
            console.print(json.dumps(active_profile.model_dump(mode="json"), indent=2))
            return

        table = Table(title=f"Plan Connection Status: {conn_id}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Connection ID", active_profile.connection_id)
        table.add_row("Platform", active_profile.platform.value)
        table.add_row("Auth Method", active_profile.auth_kind.value)
        table.add_row("Account", active_profile.account_label)
        table.add_row("Tier", active_profile.tier)
        table.add_row("Status", active_profile.status.value)
        table.add_row(
            "Last Validated",
            active_profile.last_validated_at.isoformat()
            if active_profile.last_validated_at
            else "Never",
        )
        if active_profile.error_message:
            table.add_row("Error", active_profile.error_message)
        models_str = ", ".join(active_profile.models) if active_profile.models else "none"
        table.add_row("Models", models_str)
        console.print(table)

    elif action == "disconnect":
        if not target:
            console.print("[red]Missing connection ID for disconnect.[/red]")
            sys.exit(1)
        conn_id = target

        found_to_delete = gateway.get_plan_connection(
            conn_id
        ) or gateway.credential_store.get_profile(conn_id)
        if not found_to_delete:
            console.print(f"[red]Connection '{conn_id}' not found.[/red]")
            sys.exit(1)

        if found_to_delete.platform in (
            ConnectionPlatform.CHATGPT_PLAN,
            ConnectionPlatform.OPENAI,
        ):
            oauth_client = OpenAIOAuthClient(store=gateway.credential_store)
            try:
                oauth_client.revoke_and_disconnect(conn_id)
            except Exception:
                pass

        gateway.remove_plan_connection(conn_id, delete_stored=True)
        console.print(
            f"[green]✓ Successfully disconnected and purged credentials for '{conn_id}'.[/green]"
        )

    else:
        console.print(
            f"[red]Unknown model action '{action}'. "
            "Use connect, connection, list, or disconnect.[/red]"
        )
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="myagentos", description="Agentic OS CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=False)

    # run command (§8 E2E execution)
    p_run = subparsers.add_parser("run", help="Run autonomous code task end-to-end")
    p_run.add_argument("prompt", help="Task prompt or goal description")
    p_run.add_argument("--repo", default=".", help="Repository root path")
    p_run.add_argument("--auto-approve", action="store_true", help="Auto-approve plan and diff")
    p_run.add_argument("--model", default="mock", help="Model ID for Planner and Worker")
    p_run.add_argument(
        "--connection",
        default=None,
        help="Plan connection ID (e.g. conn_chatgpt_plus, conn_claude_cli)",
    )

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
    p_bench = subparsers.add_parser(
        "benchmark",
        aliases=["bench"],
        help="Run empirical benchmark suite (§26, §28)",
    )
    p_bench.add_argument(
        "--suite",
        default="smoke",
        choices=["smoke", "full", "security", "pca"],
        help="Benchmark task suite to execute (default: smoke)",
    )
    p_bench.add_argument(
        "--output",
        default=None,
        help="Path to save output JSON benchmark report",
    )
    p_bench.add_argument(
        "--model",
        default="mock",
        help="Model ID to evaluate across both baseline and myagentos",
    )
    p_bench.add_argument(
        "--harness-only",
        action="store_true",
        help="Run legacy routing-only harness instead of full comparative evaluation",
    )

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

    # categorize command (§21)
    p_categorize = subparsers.add_parser("categorize", help="Scan and categorize project (§21)")
    p_categorize.add_argument("--repo", default=".", help="Repository root path")
    p_categorize.add_argument("--force", action="store_true", help="Force re-scan")
    p_categorize.add_argument("--json", action="store_true", help="Output JSON profile")

    # project command (§21 & Project Manager)
    p_proj = subparsers.add_parser("project", help="Manage projects and project explorer")
    p_proj.add_argument(
        "action",
        nargs="?",
        choices=[
            "list",
            "add",
            "new",
            "clone",
            "trash",
            "categorize",
            "profile",
            "tags",
            "init",
            "reset",
        ],
        help="Action to execute (default: list)",
    )
    p_proj.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target project ID, path, URL, or trash sub-action (list, move, restore, purge)",
    )
    p_proj.add_argument(
        "secondary",
        nargs="?",
        default=None,
        help="Secondary target (clone destination path or project ID for trash)",
    )
    p_proj.add_argument("--name", default=None, help="Project name")
    p_proj.add_argument("--repo", default=".", help="Repository root path")
    p_proj.add_argument("--tag", default=None, help="Filter by tag label")
    p_proj.add_argument("--search", default=None, help="Search query filter")
    p_proj.add_argument("--force", action="store_true", help="Force re-scan")
    p_proj.add_argument("--confirm", action="store_true", help="Confirm permanent deletion")
    p_proj.add_argument("--json", action="store_true", help="Output as JSON")

    # mya command (§24 of mya-commands spec)
    p_mya = subparsers.add_parser(
        "mya", help="Execute Mya command or launch interactive terminal (§24)"
    )
    p_mya.add_argument(
        "command",
        nargs="?",
        default=None,
        help="Mya command to execute (e.g. /info, /monitor, /fast, /security)",
    )
    p_mya.add_argument("argument", nargs="?", default="", help="Command argument or prompt")
    p_mya.add_argument("--repo", default=".", help="Repository root path")

    # setup command (§24 First Run Setup)
    p_setup = subparsers.add_parser("setup", help="Run first-time setup for Mya and Mya Home (§24)")
    p_setup.add_argument("--name", default=None, help="User display name preference")
    p_setup.add_argument(
        "--theme",
        default=None,
        choices=["default", "minimal", "high_contrast", "monochrome"],
        help="Visual UI theme preference",
    )
    p_setup.add_argument("--mya-home", default=None, help="Custom directory path for Mya Home")
    p_setup.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run setup non-interactively with defaults or provided arguments",
    )
    p_setup.add_argument(
        "--force",
        action="store_true",
        help="Force re-setup even if already configured",
    )

    # model command (§AO-MODEL-PLAN-CONNECT-01)
    p_model = subparsers.add_parser(
        "model",
        help="Manage model subscription plan connections (§AO-MODEL-PLAN-CONNECT-01)",
    )
    p_model.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["connect", "connection", "list", "status", "disconnect"],
        help="Model management action (connect, connection, list, status, disconnect)",
    )
    p_model.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Provider (openai/claude), sub-action (list/status), or connection ID",
    )
    p_model.add_argument(
        "sub_target",
        nargs="?",
        default=None,
        help="Secondary parameter (e.g. connection ID for 'connection status')",
    )
    p_model.add_argument(
        "--auth",
        default=None,
        choices=["oauth", "cli"],
        help="Authentication method (oauth or cli)",
    )
    p_model.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open browser automatically for OAuth",
    )
    p_model.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh connection token or status",
    )
    p_model.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    if args.subcommand is None:
        from myagentos.ui.app import run as run_mya

        run_mya()
        return

    if args.subcommand == "run":
        cmd_run(
            prompt=args.prompt,
            repo_path=args.repo,
            auto_approve=args.auto_approve,
            model_id=args.model,
            connection_id=getattr(args, "connection", None),
        )
    elif args.subcommand == "route":
        cmd_route(args.prompt)
    elif args.subcommand == "status":
        cmd_status(args.job_id)
    elif args.subcommand == "verify":
        cmd_verify(args.job_id)
    elif args.subcommand in ("benchmark", "bench"):
        cmd_benchmark(
            suite=args.suite,
            output_path=args.output,
            model_id=args.model,
            harness_only=args.harness_only,
        )
    elif args.subcommand == "continue":
        cmd_continue(action=args.action, repo_path=args.repo, dynamic=args.dynamic)
    elif args.subcommand == "categorize":
        cmd_categorize(repo_path=args.repo, force=args.force, json_output=args.json)
    elif args.subcommand == "project":
        cmd_project(
            action=args.action,
            target=args.target,
            secondary=args.secondary,
            name=args.name,
            repo_path=args.repo,
            tag=args.tag,
            search=args.search,
            json_output=args.json,
            force=args.force,
            confirm=args.confirm,
        )
    elif args.subcommand == "mya":
        cmd_mya(
            command=args.command,
            argument=args.argument,
            repo_path=args.repo,
        )
    elif args.subcommand == "setup":
        cmd_setup(
            name=args.name,
            theme=args.theme,
            mya_home=args.mya_home,
            non_interactive=args.non_interactive,
            force=args.force,
        )
    elif args.subcommand == "model":
        cmd_model(
            action=args.action,
            target=args.target,
            sub_target=args.sub_target,
            auth=args.auth,
            no_browser=args.no_browser,
            refresh=args.refresh,
            json_output=args.json,
        )


if __name__ == "__main__":
    main()
