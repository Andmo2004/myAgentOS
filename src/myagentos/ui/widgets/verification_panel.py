"""Verification results and guard check panel widget (§6.5)."""

from typing import Any

from textual.widgets import Static

from myagentos.ui.theme.symbols import get_status_symbol
from myagentos.ui.theme.themes import ThemeRegistry
from myagentos.ui.visual.state import VerificationViewModel


class VerificationPanelWidget(Static):
    """Renders test suite, lint, type checks, and policy check outcomes (§6.5)."""

    def __init__(
        self,
        view_model: VerificationViewModel | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.view_model = view_model or VerificationViewModel()
        super().__init__(*args, **kwargs)

    def set_view_model(self, vm: VerificationViewModel) -> None:
        self.view_model = vm
        self.refresh()

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        ascii_only = theme.ascii_only
        overall_sym = get_status_symbol(self.view_model.overall_status, ascii_only=ascii_only)

        stat_val = self.view_model.overall_status.value
        lines: list[str] = [
            f"[bold cyan]VERIFICATION SUITE[/bold cyan] ({overall_sym} {stat_val})",
            "",
        ]

        for check in self.view_model.checks:
            sym = get_status_symbol(check.status, ascii_only=ascii_only)
            detail = f" [dim]- {check.detail}[/dim]" if check.detail else ""
            lines.append(f"  {sym} {check.label:<18}{detail}")

        return "\n".join(lines)
