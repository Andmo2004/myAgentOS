"""File activity widget categorizing files by lifecycle stage (§11)."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from textual.widgets import Static

from myagentos.ui.theme.symbols import (
    ASCII_FILE_ACTIVITY_BADGES,
    FILE_ACTIVITY_BADGES,
    FileActivityState,
)
from myagentos.ui.theme.themes import ThemeRegistry
from myagentos.ui.visual.state import FileActivityViewModel


class FileActivityWidget(Static):
    """Categorizes and displays files strictly by state (§11).

    States: READ, TOUCHED, MODIFIED, PROPOSED, VERIFIED.
    """

    def __init__(
        self,
        activities: Sequence[FileActivityViewModel] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.activities: list[FileActivityViewModel] = list(activities or [])
        super().__init__(*args, **kwargs)

    def set_activities(self, activities: Sequence[FileActivityViewModel]) -> None:
        self.activities = list(activities)
        self.refresh()

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        ascii_only = theme.ascii_only
        badges = ASCII_FILE_ACTIVITY_BADGES if ascii_only else FILE_ACTIVITY_BADGES

        if not self.activities:
            return "[dim]No file activity observed[/dim]"

        grouped: dict[FileActivityState, list[FileActivityViewModel]] = defaultdict(list)
        for act in self.activities:
            grouped[act.state].append(act)

        lines: list[str] = ["[bold cyan]FILE ACTIVITY LIFECYCLE[/bold cyan]", ""]
        order = [
            FileActivityState.READ,
            FileActivityState.TOUCHED,
            FileActivityState.MODIFIED,
            FileActivityState.PROPOSED,
            FileActivityState.VERIFIED,
        ]

        for state in order:
            items = grouped.get(state)
            if not items:
                continue

            badge = badges[state]
            lines.append(f"{badge}")
            for item in items:
                agent_lbl = f" [dim]({item.agent_id})[/dim]" if item.agent_id else ""
                lines.append(f"  • {item.file_path}{agent_lbl}")
            lines.append("")

        return "\n".join(lines).strip()
