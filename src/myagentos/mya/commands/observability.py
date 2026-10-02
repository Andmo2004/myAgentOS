"""Observability and Telemetry service for Mya Commands.

Implements /info, /telemetry, and /monitor according to §6, §8, §9 of
docs/agentic-os-feature-mya-commands.md.
"""

from __future__ import annotations

from typing import Any

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.mya.commands.models import (
    AgentActivitySnapshot,
    AgentDisplayConfig,
    LiveAgentState,
    ObservedFileState,
    format_command_badge,
)
from myagentos.ui.session import Session


class ObservabilityService:
    """Service producing deterministic projections for /info, /telemetry, and /monitor.

    Follows §6, §8, §9 of docs/agentic-os-feature-mya-commands.md.
    """

    def __init__(
        self,
        event_store: EventStore | None = None,
        display_config: AgentDisplayConfig | None = None,
    ) -> None:
        self.event_store = event_store or EventStore()
        self.display_config = display_config or AgentDisplayConfig()

    def get_token_breakdown(self, job_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Calculates token and cost consumption broken down by agent role."""
        breakdown: dict[str, dict[str, Any]] = {
            "Planner": {"calls": 0, "input": 0, "output": 0, "cost": 0.0},
            "Worker": {"calls": 0, "input": 0, "output": 0, "cost": 0.0},
            "Reviewer": {"calls": 0, "input": 0, "output": 0, "cost": 0.0},
            "Mya": {"calls": 0, "input": 0, "output": 0, "cost": 0.0},
            "Router": {"calls": 0, "input": 0, "output": 0, "cost": 0.0},
        }

        if not job_id:
            return breakdown

        events = self.event_store.load_events(job_id)
        for ev in events:
            role = "Worker"
            if ev.actor == EventActor.PLANNER:
                role = "Planner"
            elif ev.actor in (EventActor.INDEPENDENT_REVIEWER, EventActor.VERIFICATION_GUARD):
                role = "Reviewer"
            elif ev.actor == EventActor.MYA:
                role = "Mya"
            elif ev.actor == EventActor.ROUTER:
                role = "Router"
            elif ev.actor == EventActor.WORKER:
                role = "Worker"

            if ev.event_name == EventName.MODEL_CALL_COMPLETED:
                p = ev.payload or {}
                breakdown[role]["calls"] += 1
                in_tok = int(p.get("input_tokens", 0) or p.get("prompt_tokens", 0))
                out_tok = int(p.get("output_tokens", 0) or p.get("completion_tokens", 0))
                breakdown[role]["input"] += in_tok
                breakdown[role]["output"] += out_tok
                breakdown[role]["cost"] += float(p.get("cost_usd", 0.0) or 0.0)

        return breakdown

    def get_agent_activities(self, job_id: str | None = None) -> list[AgentActivitySnapshot]:
        """Gathers agent telemetry and state with friendly display names (§8, §9)."""
        breakdown = self.get_token_breakdown(job_id)

        # Baseline agents to report
        agent_defs = [
            ("mya", "Mya", "Mya"),
            ("planner", "Architect", "Planner"),
            ("worker_1", "Builder", "Worker"),
            ("worker_2", "Debugger", "Worker"),
            ("reviewer", "Guardian", "Reviewer"),
            ("router", "Navigator", "Router"),
        ]

        snapshots: list[AgentActivitySnapshot] = []
        for agent_id, default_display, role in agent_defs:
            display_name = self.display_config.get_display_name(agent_id)
            metrics = breakdown.get(role, {"calls": 0, "input": 0, "output": 0, "cost": 0.0})

            # Determine live state from events if job active
            state = LiveAgentState.IDLE
            current_task = ""
            files: dict[str, ObservedFileState] = {}

            if job_id:
                events = self.event_store.load_events(job_id)
                for ev in events:
                    # Check task context
                    if ev.event_name == EventName.WORKER_CONTEXT_BUILT:
                        for f in ev.payload.get("context_files", []):
                            files[f] = ObservedFileState.READ
                    elif ev.event_name == EventName.PLAN_GENERATED:
                        for f in ev.payload.get("target_files", []):
                            files[f] = ObservedFileState.PROPOSED
                    elif ev.event_name == EventName.APPROVAL_REQUESTED:
                        for f in ev.payload.get("modified_files", []):
                            files[f] = ObservedFileState.MODIFIED
                    elif ev.event_name == EventName.APPROVAL_GRANTED:
                        for f in ev.payload.get("modified_files", []):
                            files[f] = ObservedFileState.VERIFIED

                last_event = events[-1] if events else None
                if last_event:
                    if last_event.actor.value == agent_id.upper() or (
                        role == "Planner" and last_event.actor == EventActor.PLANNER
                    ):
                        state = LiveAgentState.WORKING
                    elif last_event.state in ("COMPLETE", "MERGED"):
                        state = LiveAgentState.COMPLETED

            snapshots.append(
                AgentActivitySnapshot(
                    agent_id=agent_id,
                    display_name=display_name,
                    role=role,
                    state=state,
                    current_task=current_task,
                    files=files,
                    calls=metrics["calls"],
                    input_tokens=metrics["input"],
                    output_tokens=metrics["output"],
                    cost_usd=metrics["cost"],
                )
            )

        return snapshots

    def render_info(
        self,
        session: Session | None = None,
        gateway: Any | None = None,
        model_id: str | None = None,
        provider: str | None = None,
    ) -> str:
        """Renders session status, identity, token distribution and budget summary (§6.1, §16)."""
        job_id = session.current_job_id if session else None
        proj_name = session.repository if session and session.repository else "none"
        mode = session.active_mode if session else "normal"

        breakdown = self.get_token_breakdown(job_id)
        total_used = sum(b["input"] + b["output"] for b in breakdown.values())
        total_budget = 100_000
        remaining_budget = max(0, total_budget - total_used)
        total_cost = sum(b["cost"] for b in breakdown.values())
        estimated_remaining_cost = max(0.0, (remaining_budget / total_budget) * 0.5)

        model_name = (
            model_id or (getattr(session, "model_id", None) if session else None) or "mock-mya"
        )
        resolved_provider = provider
        if not resolved_provider:
            if model_name.startswith("mock"):
                resolved_provider = "mock"
            elif "gpt" in model_name or "o1" in model_name or "o3" in model_name:
                resolved_provider = "openai"
            elif "claude" in model_name or "anthropic" in model_name:
                resolved_provider = "anthropic"
            elif "gemini" in model_name or "google" in model_name:
                resolved_provider = "google"
            else:
                resolved_provider = "mock"

        deployment_type = "LOCAL" if resolved_provider == "mock" else "REMOTE"

        lines = [
            format_command_badge("/info") + " [bold]SESSION INFORMATION[/bold]",
            "",
            "[bold cyan]── MYA & MODEL ──────────────────────────[/bold cyan]",
            f"  Model:       [bold cyan]{model_name}[/bold cyan]",
            f"  Deployment:  [bold]{deployment_type}[/bold]",
            f"  Provider:    [bold]{resolved_provider.capitalize()}[/bold]",
            "",
        ]

        if gateway is not None:
            profile = gateway.get_credential_profile(resolved_provider)
            if profile:
                is_valid = str(profile.status).lower() in ("valid", "credentialstatus.valid")
                status_icon = "✓" if is_valid else "✗"
                status_style = "bold green" if is_valid else "bold red"
                status_name = (
                    profile.status.name
                    if hasattr(profile.status, "name")
                    else str(profile.status).upper()
                )
                status_display = f"[{status_style}]{status_icon} {status_name}[/{status_style}]"
                lines.extend(
                    [
                        "[bold cyan]── CREDENTIAL ───────────────────────────[/bold cyan]",
                        f"  Status:      {status_display}",
                        f"  Source:      {profile.source}",
                        f"  Profile:     {profile.credential_id}",
                        f"  Fingerprint: [dim]{profile.fingerprint}[/dim]",
                    ]
                )
                if profile.identity:
                    if profile.identity.organization:
                        lines.append(f"  Account:     {profile.identity.organization}")
                    if profile.identity.project:
                        lines.append(f"  Project:     {profile.identity.project}")
                    if profile.identity.quota_scope:
                        lines.append(f"  Quota Scope: {profile.identity.quota_scope}")
                    if not (
                        profile.identity.organization
                        or profile.identity.project
                        or profile.identity.quota_scope
                    ):
                        lines.append("  Identity:    Not provided by provider")
                else:
                    lines.append("  Identity:    Not provided by provider")
                lines.append("")

        lines.extend(
            [
                "[bold cyan]── SESSION ──────────────────────────────[/bold cyan]",
                f"  Project: [bold]{proj_name}[/bold]",
                "  Mya:     ready",
                f"  Job:     {job_id or 'none'}",
                f"  Mode:    {mode}",
                "",
                "[bold cyan]── TOKENS ───────────────────────────────[/bold cyan]",
                f"  Budget remaining: [bold green]{remaining_budget:,}[/bold green]",
                f"  Used:             [bold]{total_used:,}[/bold] / {total_budget:,}",
                "",
            ]
        )

        for role in ["Planner", "Worker", "Reviewer", "Mya", "Router"]:
            used = breakdown[role]["input"] + breakdown[role]["output"]
            lines.append(f"  {role:<12} {used:>8,}")

        lines.extend(
            [
                "",
                "[bold cyan]── COST ──────────────────────────────────────────[/bold cyan]",
                f"  Spent:               [yellow]${total_cost:.4f}[/yellow]",
                f"  Estimated remaining: [green]${estimated_remaining_cost:.4f}[/green]",
            ]
        )

        return "\n".join(lines)

    def render_telemetry(self, job_id: str | None = None) -> str:
        """Renders per-agent activity, call counts, and token usage (§8.1)."""
        snapshots = self.get_agent_activities(job_id)
        lines = [
            format_command_badge("/telemetry") + " [bold]AGENT TELEMETRY[/bold]",
            "",
        ]

        for s in snapshots:
            k_in = (
                f"{s.input_tokens / 1000:.1f}k" if s.input_tokens >= 1000 else str(s.input_tokens)
            )
            k_out = (
                f"{s.output_tokens / 1000:.1f}k"
                if s.output_tokens >= 1000
                else str(s.output_tokens)
            )
            lines.extend(
                [
                    f"[bold]{s.display_name}[/bold] [dim]({s.agent_id})[/dim]",
                    f"  calls:  {s.calls}",
                    f"  input:  {k_in}",
                    f"  output: {k_out}",
                    f"  cost:   [yellow]${s.cost_usd:.4f}[/yellow]",
                    "",
                ]
            )

        return "\n".join(lines)

    def render_monitor(self, job_id: str | None = None, session: Session | None = None) -> str:
        """Renders live monitoring view of agents and affected files (§9.1, §28)."""
        proj_name = session.repository if session and session.repository else "unknown"
        job_display = job_id or "idle"
        snapshots = self.get_agent_activities(job_id)

        lines = [
            format_command_badge("/monitor") + " [bold]AGENTIC OS · LIVE MONITOR[/bold]",
            f"[dim]Project: {proj_name} · Job: {job_display}[/dim]",
            "",
        ]

        for s in snapshots:
            state_color = "green" if s.state == LiveAgentState.WORKING else "dim"
            state_badge = f"[{state_color}]· {s.state.value}[/{state_color}]"
            lines.append(f"├── [bold]{s.display_name}[/bold] {state_badge}")

            if s.files:
                for fpath, fstate in s.files.items():
                    color = "magenta" if fstate == ObservedFileState.READ else "green"
                    lines.append(f"│   ├── [{color}]{fpath}[/{color}] [dim]({fstate.value})[/dim]")

        return "\n".join(lines)
