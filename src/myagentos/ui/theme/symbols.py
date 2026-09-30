"""Standard visual symbols, fallback representations, and status tokens.

Implements §7.1 and §11 of AO-UI-MYA-VISUAL-01.
Colors reinforce meaning; they do not define it in isolation (Accessibility by redundancy).
"""

from enum import StrEnum
from typing import Final


class VisualStatus(StrEnum):
    """Closed set of visual statuses for agents, jobs, and tasks (§7.1)."""

    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    APPROVAL = "approval"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


# Standard symbols for UTF-8 terminals
UNICODE_SYMBOLS: Final[dict[VisualStatus, str]] = {
    VisualStatus.IDLE: "○",
    VisualStatus.QUEUED: "◌",
    VisualStatus.RUNNING: "●",
    VisualStatus.WAITING: "…",
    VisualStatus.PAUSED: "Ⅱ",
    VisualStatus.APPROVAL: "!",
    VisualStatus.SUCCESS: "✓",
    VisualStatus.WARNING: "!",
    VisualStatus.FAILED: "×",
    VisualStatus.BLOCKED: "⊘",
    VisualStatus.CANCELLED: "■",
}

# Plain ASCII fallbacks for limited or monochrome terminals (§7.1)
ASCII_SYMBOLS: Final[dict[VisualStatus, str]] = {
    VisualStatus.IDLE: "(o)",
    VisualStatus.QUEUED: "[q]",
    VisualStatus.RUNNING: "(*)",
    VisualStatus.WAITING: "...",
    VisualStatus.PAUSED: "||",
    VisualStatus.APPROVAL: "[!]",
    VisualStatus.SUCCESS: "[v]",
    VisualStatus.WARNING: "[!]",
    VisualStatus.FAILED: "[x]",
    VisualStatus.BLOCKED: "[/]",
    VisualStatus.CANCELLED: "[-]",
}


class Severity(StrEnum):
    """System severity levels (§7.2). Independent of risk and cost."""

    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class CostTier(StrEnum):
    """Relative token consumption tiers (§7.3) with textual redundancy."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY HIGH"


COST_TIER_BADGES: Final[dict[CostTier, str]] = {
    CostTier.LOW: "🟢 [LOW]",
    CostTier.MEDIUM: "🟡 [MEDIUM]",
    CostTier.HIGH: "🟠 [HIGH]",
    CostTier.VERY_HIGH: "🔴 [VERY HIGH]",
}

ASCII_COST_TIER_BADGES: Final[dict[CostTier, str]] = {
    CostTier.LOW: "[LOW]",
    CostTier.MEDIUM: "[MED]",
    CostTier.HIGH: "[HIGH]",
    CostTier.VERY_HIGH: "[V_HIGH]",
}


class FileActivityState(StrEnum):
    """File lifecycle activity states (§11).

    'TOUCHED' indicates access/preparation; 'MODIFIED' indicates byte changes.
    """

    READ = "READ"
    TOUCHED = "TOUCHED"
    MODIFIED = "MODIFIED"
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"


FILE_ACTIVITY_BADGES: Final[dict[FileActivityState, str]] = {
    FileActivityState.READ: "[cyan][READ][/cyan]",
    FileActivityState.TOUCHED: "[yellow][TOUCHED][/yellow]",
    FileActivityState.MODIFIED: "[magenta][MODIFIED][/magenta]",
    FileActivityState.PROPOSED: "[blue][PROPOSED][/blue]",
    FileActivityState.VERIFIED: "[green][VERIFIED][/green]",
}

ASCII_FILE_ACTIVITY_BADGES: Final[dict[FileActivityState, str]] = {
    FileActivityState.READ: "[READ]",
    FileActivityState.TOUCHED: "[TOUCH]",
    FileActivityState.MODIFIED: "[MOD]",
    FileActivityState.PROPOSED: "[PROP]",
    FileActivityState.VERIFIED: "[VERIF]",
}


def get_status_symbol(status: VisualStatus | str, ascii_only: bool = False) -> str:
    """Returns the visual symbol for a given status, with ASCII fallback."""
    if isinstance(status, str):
        try:
            status = VisualStatus(status.lower())
        except ValueError:
            return "?" if ascii_only else "•"

    table = ASCII_SYMBOLS if ascii_only else UNICODE_SYMBOLS
    return table.get(status, "?" if ascii_only else "•")
