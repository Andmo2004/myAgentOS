"""Agent execution tree widget (§6.3, §12)."""

from collections.abc import Sequence
from typing import Any

from textual.widgets import Static

from myagentos.ui.theme.symbols import VisualStatus, get_status_symbol
from myagentos.ui.theme.themes import ThemeRegistry
from myagentos.ui.visual.state import AgentViewModel


class AgentTreeWidget(Static):
    """Renders active agent hierarchy and live states (§6.3, §12)."""

    def __init__(
        self,
        agents: Sequence[AgentViewModel] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.agents: list[AgentViewModel] = list(agents or [])
        super().__init__(*args, **kwargs)

    def set_agents(self, agents: Sequence[AgentViewModel]) -> None:
        self.agents = list(agents)
        self.refresh()

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        ascii_only = theme.ascii_only

        if not self.agents:
            idle_sym = get_status_symbol(VisualStatus.IDLE, ascii_only=ascii_only)
            return f"[dim]{idle_sym} No active agents[/dim]"

        lines: list[str] = ["[bold cyan]AGENTS EXECUTION TREE[/bold cyan]", ""]
        total = len(self.agents)

        for i, a in enumerate(self.agents):
            is_last = i == total - 1
            branch = "`-- " if ascii_only else ("└── " if is_last else "├── ")
            sub_indent = "    " if is_last else ("│   " if not ascii_only else "|   ")

            sym = get_status_symbol(a.status, ascii_only=ascii_only)
            lines.append(f"{branch}{sym} [bold]{a.display_name}[/bold] ({a.role})")
            if a.current_activity:
                lines.append(f"{sub_indent}  [dim]task:[/dim] {a.current_activity}")
            if a.files:
                for f in a.files:
                    lines.append(f"{sub_indent}  [dim]file:[/dim] {f}")
            if a.input_tokens > 0 or a.output_tokens > 0:
                lines.append(
                    f"{sub_indent}  [dim]tokens:[/dim] in:{a.input_tokens} out:{a.output_tokens}"
                )

        return "\n".join(lines)
