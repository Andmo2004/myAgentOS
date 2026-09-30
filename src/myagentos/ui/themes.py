"""Visual design tokens for the interactive UI.

Uses symbols that work in monochrome terminals (§39).
Color is an additional signal, never the only one.
"""


# Status icons — must work without color
class Icons:
    PASS = "✓"
    FAIL = "✗"
    WARNING = "!"
    RUNNING = "●"
    PENDING = "○"
    ARROW = "›"
    PROMPT = "mya ›"
    SEPARATOR = "─"


# Color palette for Rich markup
class Colors:
    PRIMARY = "cyan"
    SUCCESS = "green"
    WARNING = "yellow"
    ERROR = "red"
    DIM = "dim"
    ACCENT = "magenta"
    INFO = "blue"
    MUTED = "dim white"


# Risk level colors
RISK_COLORS: dict[str, str] = {
    "LOW": "green",
    "MEDIUM": "yellow",
    "HIGH": "red",
    "CRITICAL": "bold red",
}
