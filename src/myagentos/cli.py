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


def main() -> None:
    parser = argparse.ArgumentParser(prog="myagentos", description="Agentic OS CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

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

    args = parser.parse_args()

    if args.subcommand == "route":
        cmd_route(args.prompt)
    elif args.subcommand == "status":
        cmd_status(args.job_id)
    elif args.subcommand == "verify":
        cmd_verify(args.job_id)
    elif args.subcommand == "benchmark":
        cmd_benchmark()


if __name__ == "__main__":
    main()
