"""Live composite job monitor widget (§6.3, §25)."""

from typing import Any

from textual.widgets import Static

from myagentos.ui.theme.symbols import get_status_symbol
from myagentos.ui.theme.themes import ThemeRegistry
from myagentos.ui.visual.state import (
    AgentViewModel,
    FileActivityViewModel,
    JobViewModel,
    VerificationViewModel,
)
from myagentos.ui.widgets.agent_tree import AgentTreeWidget
from myagentos.ui.widgets.file_activity import FileActivityWidget
from myagentos.ui.widgets.token_meter import TokenMeterWidget
from myagentos.ui.widgets.verification_panel import VerificationPanelWidget


class JobMonitorWidget(Static):
    """Composite monitor rendering execution tree, files, meter, and checks."""

    def __init__(
        self,
        job: JobViewModel | None = None,
        agents: list[AgentViewModel] | None = None,
        files: list[FileActivityViewModel] | None = None,
        verification: VerificationViewModel | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.job = job
        self.agents = agents or []
        self.files = files or []
        self.verification = verification or VerificationViewModel()
        super().__init__(*args, **kwargs)

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        ascii_only = theme.ascii_only

        parts: list[str] = []
        if self.job:
            sym = get_status_symbol(self.job.status, ascii_only=ascii_only)
            parts.append(
                f"[bold cyan]JOB {self.job.job_id}[/bold cyan]  {self.job.title}\n"
                f"{sym} [{self.job.status.value.upper()}]  "
                f"[dim]risk:[/dim] [yellow]{self.job.risk}[/yellow]  "
                f"[dim]cost:[/dim] [green]${self.job.cost_usd:.4f}[/green]"
            )
            parts.append("")

        # Render subcomponents
        if self.agents:
            agent_tree = AgentTreeWidget(self.agents)
            parts.append(agent_tree.render())
            parts.append("")

        if self.files:
            file_widget = FileActivityWidget(self.files)
            parts.append(file_widget.render())
            parts.append("")

        # Token meter
        total_in = sum(a.input_tokens for a in self.agents)
        total_out = sum(a.output_tokens for a in self.agents)
        total_cost = sum(a.cost_usd for a in self.agents)
        if self.job:
            total_cost = max(total_cost, self.job.cost_usd)

        token_meter = TokenMeterWidget(
            used_tokens=total_in + total_out,
            budget_tokens=50000,
            cost_usd=total_cost,
        )
        parts.append(token_meter.render())
        parts.append("")

        if self.verification.checks:
            verif_widget = VerificationPanelWidget(self.verification)
            parts.append(verif_widget.render())

        return "\n".join(parts).strip()
