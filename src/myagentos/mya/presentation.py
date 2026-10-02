"""Mya visual character presentation semantics and pluggable renderers.

Implements §14, §15, §16, §19, §34, and §35 of AO-UI-MYA-VISUAL-01.

Crucial Architectural Invariants (§4.5, §15):
- Presentation-only state.
- NEVER modifies Job FSM, Capability Tokens, Policy Risk, or Security Authorization.
- 0 LLM token overhead (§30).
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class MyaSemanticState(StrEnum):
    """Mya presentation state machine (§16).

    Independent of Job Controller FSM. Represents presentation and dialogue state.
    """

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    RESEARCHING = "RESEARCHING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    WAITING_USER = "WAITING_USER"
    APPROVAL_NEEDED = "APPROVAL_NEEDED"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class MyaPresentationState(BaseModel):
    """Independent presentation-only state model for Mya (§15).

    Never used to grant authority, lower risk, or bypass security rules.
    """

    model_config = ConfigDict(frozen=True)

    expression: str = "calm"  # calm | focused | curious | thoughtful | alert | satisfied
    pose: str = "neutral"  # neutral | listening | presenting | observing
    activity: str = "idle"  # idle | analyzing | researching | monitoring | speaking | waiting_user
    attention: str = "project"  # user | project | job | diff | verification
    speech_mode: str = "concise"  # concise | detailed | scientific | warning
    confidence_visual: str = "high"  # high | moderate | cautious


class MyaRenderState(BaseModel):
    """Normalized payload passed to visual renderers (§34).

    Contains presentation tokens without coupling to model gateway or LLM internals.
    """

    model_config = ConfigDict(frozen=True)

    status: str = "IDLE"
    label: str = "Ready"
    expression: str = "calm"
    activity: str = "idle"
    emphasis: str = "normal"
    avatar_mode: str = "dot"  # dot | glyph | ascii | minimal
    details: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class MyaRenderer(Protocol):
    """Contract for rendering Mya's presence, avatar, and speech (§35)."""

    def render_presence(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        """Renders single-line presence indicator."""
        ...

    def render_avatar(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        """Renders multi-line visual avatar."""
        ...

    def render_speech_bubble(
        self,
        message: str,
        state: MyaRenderState,
        ascii_only: bool = False,
    ) -> str:
        """Renders speech message with Mya visual frame."""
        ...


class DotMyaRenderer:
    """Phase A — Dot / Presence renderer (§14.2.A).

    Minimal, non-intrusive dot presence (`● Mya`).
    """

    def render_presence(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        status_upper = state.status.upper()
        if status_upper in ("PROCESSING", "RESEARCHING", "THINKING"):
            sym = "(*)" if ascii_only else "●"
            color = "cyan"
        elif status_upper == "APPROVAL_NEEDED":
            sym = "[!]" if ascii_only else "!"
            color = "yellow"
        elif status_upper == "SUCCESS":
            sym = "[v]" if ascii_only else "✓"
            color = "green"
        elif status_upper in ("WARNING", "ERROR"):
            sym = "[x]" if ascii_only else "×"
            color = "red"
        else:
            sym = "(o)" if ascii_only else "○"
            color = "dim"

        label = f"[{state.expression}]" if state.expression != "calm" else ""
        return f"[{color}]{sym}[/{color}] [bold]Mya[/bold] [dim]{label} {state.label}[/dim]".strip()

    def render_avatar(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        return self.render_presence(state, ascii_only)

    def render_speech_bubble(
        self,
        message: str,
        state: MyaRenderState,
        ascii_only: bool = False,
    ) -> str:
        hdr = self.render_presence(state, ascii_only)
        return f"{hdr}\n{message}"


class GlyphMyaRenderer:
    """Phase B — Framed glyph renderer (§14.2.B)."""

    def render_presence(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        sym = "(*)" if ascii_only else "◌"
        return f"[bold cyan]{sym} Mya[/bold cyan] [dim]· {state.label}[/dim]"

    def render_avatar(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        sym = "(*)" if ascii_only else "◌"
        top = "+- Mya ------------+" if ascii_only else "╭─ Mya ─────────────╮"
        mid = f"|   {sym:<16}|" if ascii_only else f"│   {sym:<16}│"
        bot = "+-------------------+" if ascii_only else "╰───────────────────╯"
        return f"[cyan]{top}\n{mid}\n{bot}[/cyan]"

    def render_speech_bubble(
        self,
        message: str,
        state: MyaRenderState,
        ascii_only: bool = False,
    ) -> str:
        top = (
            "+- Mya ---------------------------------------------+"
            if ascii_only
            else ("╭─ Mya ─────────────────────────────────────────────╮")
        )
        bot = (
            "+---------------------------------------------------+"
            if ascii_only
            else ("╰───────────────────────────────────────────────────╯")
        )
        return f"[cyan]{top}[/cyan]\n{message}\n[cyan]{bot}[/cyan]"


class AsciiMyaRenderer:
    """Phase C — Composite Character Avatar with reactive facial expressions (§14.2.C)."""

    # Expression maps: (eyes, mouth)
    _EXPRESSIONS: dict[str, tuple[str, str]] = {
        "calm": ("◉ ◉", "◡"),
        "focused": ("• •", "─"),
        "curious": ("o O", "~"),
        "thoughtful": ("· ·", "ᵕ"),
        "alert": ("! !", "o"),
        "satisfied": ("^ ^", "◡"),
    }

    _ASCII_EXPRESSIONS: dict[str, tuple[str, str]] = {
        "calm": ("o o", "-"),
        "focused": ("* *", "="),
        "curious": ("o O", "~"),
        "thoughtful": (". .", "-"),
        "alert": ("! !", "o"),
        "satisfied": ("^ ^", "v"),
    }

    def render_presence(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        dot_rend = DotMyaRenderer()
        return dot_rend.render_presence(state, ascii_only)

    def render_avatar(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        expr = state.expression.lower()
        table = self._ASCII_EXPRESSIONS if ascii_only else self._EXPRESSIONS
        eyes, mouth = table.get(expr, table["calm"])

        if ascii_only:
            return f"  +-----+\n  | {eyes} |\n  |  {mouth}  |\n  +-----+\n   Mya"

        return f"  ╭─────╮\n  │ {eyes} │\n  │  {mouth}  │\n  ╰─────╯\n   Mya"

    def render_speech_bubble(
        self,
        message: str,
        state: MyaRenderState,
        ascii_only: bool = False,
    ) -> str:
        avatar = self.render_avatar(state, ascii_only)
        lines = [f"[cyan]{avatar}[/cyan]", "", message]
        return "\n".join(lines)


class MinimalMyaRenderer:
    """Compact single-line tag representation for high density."""

    def render_presence(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        return f"[bold cyan][Mya][/bold cyan] [dim]{state.label}[/dim]"

    def render_avatar(self, state: MyaRenderState, ascii_only: bool = False) -> str:
        return self.render_presence(state, ascii_only)

    def render_speech_bubble(
        self,
        message: str,
        state: MyaRenderState,
        ascii_only: bool = False,
    ) -> str:
        return f"[bold cyan][Mya][/bold cyan]: {message}"


def get_mya_renderer(avatar_mode: str = "dot") -> MyaRenderer:
    """Resolves renderer for a requested avatar mode."""
    mode = avatar_mode.strip().lower()
    if mode == "glyph":
        return GlyphMyaRenderer()
    if mode == "ascii":
        return AsciiMyaRenderer()
    if mode == "minimal":
        return MinimalMyaRenderer()
    return DotMyaRenderer()
