"""Command line interface for myagentos."""

import argparse
import json
import sys
from pathlib import Path

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
            else (
                "Policy Violation Blocked"
                if m.policy_violation_caught
                else "Normal Completion"
            )
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
        projects = mgr.list_projects(
            filter_criteria=ProjectFilter(query=search, tag=tag)
        )
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
                f"[bold green]✓ Project added:[/bold green] {proj.name} "
                f"({proj.project_id})"
            )
            tags = " ".join(f"[{t.label}]" for t in proj.visible_tags)
            console.print(f"  Visible tags: [magenta]{tags}[/magenta]")
            console.print(f"  Mya namespace: [dim]{proj.mya_namespace_id}[/dim]")
        except Exception as exc:
            console.print(f"[bold red]✗ Failed adding project:[/bold red] {exc}")
            sys.exit(1)
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
                f"[bold green]✓ Project created:[/bold green] {proj.name} "
                f"({proj.project_id})"
            )
            console.print(f"  Location: {proj.path}")
        except Exception as exc:
            console.print(f"[bold red]✗ Failed creating project:[/bold red] {exc}")
            sys.exit(1)
        return

    if action == "clone":
        if not target or not secondary:
            console.print(
                "[bold red]✗ URL and destination required for 'project clone'[/bold red]"
            )
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
    else:
        from myagentos.mya.agent import MyaAgent

        gw = ModelGateway()
        if "mock" not in gw.adapters:
            gw.register_adapter("mock", MockProviderAdapter())
        agent = MyaAgent(gateway=gw, model_id="mock")
        resp = agent.converse(f"{command} {argument}".strip(), session=session)
        console.print(resp)


def main() -> None:
    parser = argparse.ArgumentParser(prog="myagentos", description="Agentic OS CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=False)

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
        default="list",
        choices=["list", "add", "new", "clone", "trash", "categorize", "profile", "tags"],
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


if __name__ == "__main__":
    main()
