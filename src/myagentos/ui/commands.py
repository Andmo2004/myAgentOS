"""Slash command parsing for the interactive UI.

Two levels of commands:
- UI commands: /help, /status, /jobs, /exit, /diff, /clear — resolved by the UI
- Routing commands: /direct, /plan, /research — passed through to LocalRouter
- Mya commands: /mya <prompt> — passed through to Mya agent
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SlashCommandKind(StrEnum):
    """Classification of a slash command."""

    # UI-level commands (resolved locally)
    HELP = "help"
    STATUS = "status"
    JOBS = "jobs"
    JOB_DETAIL = "job"
    EXIT = "exit"
    CLEAR = "clear"
    DIFF = "diff"
    LOG = "log"
    CANCEL = "cancel"
    APPROVE = "approve"
    REJECT = "reject"
    DEBUG = "debug"
    USAGE = "usage"
    MODEL = "model"
    SETTINGS = "settings"
    AUDIT = "audit"
    VERIFY = "verify"
    TESTS = "tests"
    CATEGORIZE = "categorize"
    PROJECTS = "projects"

    # Mya Commands (§3 of mya-commands spec)
    INFO = "info"
    TELEMETRY = "telemetry"
    MONITOR = "monitor"
    FAST = "fast"
    SCI_MODE = "sci_mode"
    DEEP_RESEARCH = "deep_research"
    OPTIMIZE = "optimize"
    DECISION = "decision"
    CLOUD = "cloud"
    SECURITY = "security"

    # Mya commands (passed to Mya agent)
    MYA = "mya"

    # Natural language (not a slash command)
    NATURAL = "natural"


class ParsedCommand(BaseModel):
    """Result of parsing user input."""

    model_config = ConfigDict(frozen=True)

    kind: SlashCommandKind
    raw_input: str
    argument: str = ""


# Slash commands recognized by the UI
_SLASH_MAP: dict[str, SlashCommandKind] = {
    "/help": SlashCommandKind.HELP,
    "/status": SlashCommandKind.STATUS,
    "/jobs": SlashCommandKind.JOBS,
    "/job": SlashCommandKind.JOB_DETAIL,
    "/exit": SlashCommandKind.EXIT,
    "/quit": SlashCommandKind.EXIT,
    "/clear": SlashCommandKind.CLEAR,
    "/diff": SlashCommandKind.DIFF,
    "/log": SlashCommandKind.LOG,
    "/cancel": SlashCommandKind.CANCEL,
    "/approve": SlashCommandKind.APPROVE,
    "/reject": SlashCommandKind.REJECT,
    "/debug": SlashCommandKind.DEBUG,
    "/usage": SlashCommandKind.USAGE,
    "/model": SlashCommandKind.MODEL,
    "/settings": SlashCommandKind.SETTINGS,
    "/audit": SlashCommandKind.AUDIT,
    "/verify": SlashCommandKind.VERIFY,
    "/tests": SlashCommandKind.TESTS,
    "/categorize": SlashCommandKind.CATEGORIZE,
    "/projects": SlashCommandKind.PROJECTS,
    # Mya Commands
    "/info": SlashCommandKind.INFO,
    "/telemetry": SlashCommandKind.TELEMETRY,
    "/monitor": SlashCommandKind.MONITOR,
    "/fast": SlashCommandKind.FAST,
    "/sci_mode": SlashCommandKind.SCI_MODE,
    "/deep_research": SlashCommandKind.DEEP_RESEARCH,
    "/optimize": SlashCommandKind.OPTIMIZE,
    "/decision": SlashCommandKind.DECISION,
    "/cloud": SlashCommandKind.CLOUD,
    "/security": SlashCommandKind.SECURITY,
    "/mya": SlashCommandKind.MYA,
}

# Commands available for autocomplete
AVAILABLE_COMMANDS: list[str] = sorted(_SLASH_MAP.keys())


def parse_input(raw: str) -> ParsedCommand:
    """Parse user input into a structured command.

    Slash commands are resolved by prefix matching.
    Everything else is treated as natural language for Mya.
    """
    trimmed = raw.strip()
    if not trimmed:
        return ParsedCommand(
            kind=SlashCommandKind.NATURAL,
            raw_input=raw,
            argument="",
        )

    if trimmed.startswith("/"):
        parts = trimmed.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        kind = _SLASH_MAP.get(cmd)
        if kind is not None:
            return ParsedCommand(kind=kind, raw_input=raw, argument=arg)

        # Unknown slash command — treat as natural language
        return ParsedCommand(
            kind=SlashCommandKind.NATURAL,
            raw_input=raw,
            argument=trimmed,
        )

    # Natural language input → goes to Mya
    return ParsedCommand(
        kind=SlashCommandKind.NATURAL,
        raw_input=raw,
        argument=trimmed,
    )


def get_completions(prefix: str) -> list[str]:
    """Return slash commands matching the given prefix for autocomplete."""
    if not prefix.startswith("/"):
        return []
    return [cmd for cmd in AVAILABLE_COMMANDS if cmd.startswith(prefix.lower())]
