"""Visual design tokens and theme re-exports for the interactive UI.

Uses symbols that work in monochrome terminals (§39).
Color is an additional signal, never the only one.
"""

from myagentos.ui.theme import (
    DEFAULT_THEME,
    HIGH_CONTRAST_THEME,
    MINIMAL_THEME,
    MONOCHROME_THEME,
    CostTier,
    FileActivityState,
    Severity,
    Theme,
    ThemeRegistry,
    VisualStatus,
    get_status_symbol,
)
from myagentos.ui.theme.mya_theme import (
    MUTED as MYA_MUTED,
)
from myagentos.ui.theme.mya_theme import (
    RED,
    SAGE,
    SAND,
)


# Status icons — clean, character-driven glyphs
class Icons:
    PASS = "✓"
    FAIL = "✗"
    WARNING = "!"
    RUNNING = "●"
    PENDING = "○"
    ARROW = "›"
    PROMPT = "❯"
    SEPARATOR = "─"
    BRAND = "◆"
    BRANCH = "⎇"
    DOT = "·"
    BAR = "▎"
    COPY = "⧉"


# Color palette for Rich markup (Truecolor Mya v2 Palette)
class Colors:
    PRIMARY = "#D97BB6"
    SECONDARY = SAND
    SUCCESS = SAGE
    WARNING = SAND
    ERROR = RED
    DIM = MYA_MUTED
    ACCENT = SAND
    INFO = "#5B9DF9"
    MUTED = MYA_MUTED


COST_COLORS: dict[str, str] = {
    "low": Colors.SUCCESS,
    "medium": Colors.WARNING,
    "high": "#E2804F",
    "max": Colors.ERROR,
}


# Risk level colors
RISK_COLORS: dict[str, str] = {
    "LOW": "green",
    "MEDIUM": "yellow",
    "HIGH": "red",
    "CRITICAL": "bold red",
}

__all__ = [
    "COST_COLORS",
    "Colors",
    "CostTier",
    "DEFAULT_THEME",
    "FileActivityState",
    "HIGH_CONTRAST_THEME",
    "Icons",
    "MINIMAL_THEME",
    "MONOCHROME_THEME",
    "RISK_COLORS",
    "Severity",
    "Theme",
    "ThemeRegistry",
    "VisualStatus",
    "get_status_symbol",
]
