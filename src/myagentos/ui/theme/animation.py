"""Operational micro-animation frames and helpers (§8).

Animations are local, deterministic, and consume 0 LLM tokens (§30).
Every animation must have operational justification (§4.2).
"""

from collections.abc import Sequence
from typing import Final

# Spinner frames for indeterminate progress (§8.1.A)
UNICODE_SPINNER_FRAMES: Final[tuple[str, ...]] = (
    "⠋",
    "⠙",
    "⠹",
    "⠸",
    "⠼",
    "⠴",
    "⠦",
    "⠧",
    "⠇",
    "⠏",
)

ASCII_SPINNER_FRAMES: Final[tuple[str, ...]] = ("|", "/", "-", "\\")

# Pulse frames for active or thinking states (§8.1.B)
UNICODE_PULSE_FRAMES: Final[tuple[str, ...]] = ("●", "◉", "●", "○")
ASCII_PULSE_FRAMES: Final[tuple[str, ...]] = ("(*)", "(o)", "(*)", "( )")


class MicroAnimation:
    """Deterministic step-by-step frame sequencer."""

    def __init__(self, frames: Sequence[str]) -> None:
        if not frames:
            raise ValueError("Frames sequence cannot be empty")
        self._frames = tuple(frames)
        self._index: int = 0

    @property
    def current(self) -> str:
        return self._frames[self._index]

    def advance(self) -> str:
        self._index = (self._index + 1) % len(self._frames)
        return self.current

    def reset(self) -> None:
        self._index = 0


def get_spinner(ascii_only: bool = False) -> MicroAnimation:
    """Returns a deterministic spinner animation instance."""
    frames = ASCII_SPINNER_FRAMES if ascii_only else UNICODE_SPINNER_FRAMES
    return MicroAnimation(frames)


def get_pulse(ascii_only: bool = False) -> MicroAnimation:
    """Returns a deterministic pulse animation instance."""
    frames = ASCII_PULSE_FRAMES if ascii_only else UNICODE_PULSE_FRAMES
    return MicroAnimation(frames)


def render_progress_bar(
    ratio: float,
    width: int = 16,
    ascii_only: bool = False,
    filled_char: str | None = None,
    empty_char: str | None = None,
) -> str:
    """Renders a progress bar string (§8.1.C) with deterministic width.

    Args:
        ratio: Value between 0.0 and 1.0 (clamped if out of range).
        width: Character width of the progress bar inner track.
        ascii_only: Whether to use ASCII characters (# and -).
        filled_char: Optional override for filled character.
        empty_char: Optional override for empty character.
    """
    clamped = max(0.0, min(1.0, float(ratio)))
    inner_width = max(1, width)
    filled_len = int(round(clamped * inner_width))
    empty_len = inner_width - filled_len

    if filled_char is None:
        filled_char = "#" if ascii_only else "█"
    if empty_char is None:
        empty_char = "-" if ascii_only else "░"

    return f"{filled_char * filled_len}{empty_char * empty_len} {int(clamped * 100)}%"
