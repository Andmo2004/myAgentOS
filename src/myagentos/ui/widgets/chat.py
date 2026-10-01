"""Conversation widgets for Mya TUI: messages, thinking indicator, prompt, suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from myagentos.ui.commands import CommandInfo, search_commands
from myagentos.ui.session import Session
from myagentos.ui.theme.animation import ASCII_SPINNER_FRAMES, UNICODE_SPINNER_FRAMES
from myagentos.ui.theme.mya_theme import (
    Thinking,
    ThinkingIndicator,
    Welcome,
    WelcomePanel,
)
from myagentos.ui.themes import COST_COLORS, Colors, Icons

from rich.markdown import Markdown

MessageRole = Literal["user", "mya", "agent", "tool", "system", "error"]

_ROLE_LABELS: dict[MessageRole, str] = {
    "user": "Tú",
    "mya": f"{Icons.BRAND} Mya",
    "agent": f"{Icons.BRAND} Mya",
    "tool": "Herramienta",
    "system": "Sistema",
    "error": f"{Icons.FAIL} Error",
}


class ChatMessage(Vertical):
    """A conversation entry rendered with vertical accent bar."""

    def __init__(
        self,
        content: RenderableType,
        role: MessageRole = "mya",
        provider: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        p_class = f"p-{provider}" if provider else ""
        css_role = "agent" if role in ("agent", "mya") else role
        classes = (
            f"chat-message -{css_role} {css_role} -{role} {role} {p_class} {kwargs.pop('classes', '')}"
        ).strip()
        super().__init__(*args, classes=classes, **kwargs)
        self.role: MessageRole = role
        self.provider = provider
        self._content = content
        self._timestamp = datetime.now().strftime("%H:%M")

    def compose(self) -> ComposeResult:
        if self.role not in ("system", "tool"):
            yield Static(
                f"[b]{_ROLE_LABELS.get(self.role, self.role)}[/b]  [{Colors.DIM}]{self._timestamp}[/{Colors.DIM}]",
                classes="chat-header",
            )
        yield Static(self._content, classes="chat-body")


MessageBlock = ChatMessage


class CommandSuggestions(OptionList):
    """Floating list of slash-command suggestions shown above the prompt."""

    can_focus = False

    def show_for(self, text: str) -> bool:
        """Populate for the typed text. Returns True when suggestions are visible."""
        matches = search_commands(text) if text.startswith("/") and " " not in text else []
        self.clear_options()
        if not matches:
            self.display = False
            return False
        self.add_options(Option(self._render_option(c), id=c.name) for c in matches)
        self.highlighted = 0
        self.display = True
        return True

    @staticmethod
    def _render_option(info: CommandInfo) -> Text:
        line = Text()
        line.append(info.name, style=f"bold {Colors.PRIMARY}")
        if info.args:
            line.append(f" {info.args}", style=Colors.MUTED)
        line.pad_right(max(1, 30 - len(line.plain)))
        line.append(info.description)
        if info.cost:
            line.append("  ●", style=COST_COLORS.get(info.cost, Colors.MUTED))
        return line

    @property
    def selected_command(self) -> str | None:
        if not self.display or self.highlighted is None:
            return None
        return self.get_option_at_index(self.highlighted).id

    def move(self, delta: int) -> None:
        if self.option_count == 0:
            return
        current = self.highlighted or 0
        self.highlighted = (current + delta) % self.option_count


class PromptInput(Input):
    """Prompt input with history navigation and command-completion keys."""

    BINDINGS = [
        Binding("up", "navigate(-1)", "Anterior", show=False),
        Binding("down", "navigate(1)", "Siguiente", show=False),
        Binding("tab", "complete", "Completar", show=False, priority=True),
    ]

    class Navigate(Message):
        def __init__(self, delta: int) -> None:
            super().__init__()
            self.delta = delta

    class Complete(Message):
        pass

    def action_navigate(self, delta: int) -> None:
        self.post_message(self.Navigate(delta))

    def action_complete(self) -> None:
        self.post_message(self.Complete())
