"""Slash command parsing for the interactive UI.

Unifies UI command parsing with the canonical CommandRegistry (§49, §50, §54).
Dead commands removed as per §34-§36 of agentic-os-feature-skills.md.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from myagentos.mya.commands.models import CATEGORY_STYLES, ExpectedCost
from myagentos.mya.commands.registry import COMMAND_REGISTRY


class SlashCommandKind(StrEnum):
    """Classification of a canonical slash command."""

    # Navigation & System
    HELP = "help"
    STATUS = "status"
    PROJECTS = "projects"
    MEMORY = "memory"
    SKILLS = "skills"
    INFO = "info"
    TELEMETRY = "telemetry"
    MONITOR = "monitor"
    CLEAR = "clear"
    EXIT = "exit"
    MYA = "mya"

    # Workflow & Modes
    FAST = "fast"
    SCIENCE = "science"
    SCI_MODE = "science"  # compatibility alias
    SECURITY = "security"
    DECISION = "decision"

    # Research
    DEEP_RESEARCH = "deep_research"
    OPTIMIZE = "optimize"
    CLOUD = "cloud"

    # Configuration
    KEY = "key"
    MODEL = "model"
    CONNECT = "connect"
    ACCOUNT = "connect"  # compatibility alias
    CATEGORIZE = "categorize"
    INIT = "init"

    # Appearance
    THEME = "theme"
    MOTION = "motion"
    AVATAR = "avatar"
    DENSITY = "density"
    COMPACT = "density"  # compatibility alias
    DENSE = "density"  # compatibility alias

    # Natural language fallback
    NATURAL = "natural"


class ParsedCommand(BaseModel):
    """Result of parsing user input."""

    model_config = ConfigDict(frozen=True)

    kind: SlashCommandKind
    raw_input: str
    argument: str = ""


# Slash commands map (canonical commands + supported legacy aliases)
_SLASH_MAP: dict[str, SlashCommandKind] = {
    # Navigation & System
    "/help": SlashCommandKind.HELP,
    "/status": SlashCommandKind.STATUS,
    "/projects": SlashCommandKind.PROJECTS,
    "/memory": SlashCommandKind.MEMORY,
    "/skills": SlashCommandKind.SKILLS,
    "/info": SlashCommandKind.INFO,
    "/telemetry": SlashCommandKind.TELEMETRY,
    "/monitor": SlashCommandKind.MONITOR,
    "/clear": SlashCommandKind.CLEAR,
    "/exit": SlashCommandKind.EXIT,
    "/quit": SlashCommandKind.EXIT,
    "/mya": SlashCommandKind.MYA,
    # Workflow
    "/fast": SlashCommandKind.FAST,
    "/science": SlashCommandKind.SCIENCE,
    "/sci_mode": SlashCommandKind.SCIENCE,
    "/security": SlashCommandKind.SECURITY,
    "/decision": SlashCommandKind.DECISION,
    # Research
    "/deep-research": SlashCommandKind.DEEP_RESEARCH,
    "/deep_research": SlashCommandKind.DEEP_RESEARCH,
    "/optimize": SlashCommandKind.OPTIMIZE,
    "/cloud": SlashCommandKind.CLOUD,
    # Configuration
    "/key": SlashCommandKind.KEY,
    "/keys": SlashCommandKind.KEY,
    "/model": SlashCommandKind.MODEL,
    "/connect": SlashCommandKind.CONNECT,
    "/account": SlashCommandKind.CONNECT,
    "/categorize": SlashCommandKind.CATEGORIZE,
    "/init": SlashCommandKind.INIT,
    # Appearance
    "/theme": SlashCommandKind.THEME,
    "/motion": SlashCommandKind.MOTION,
    "/avatar": SlashCommandKind.AVATAR,
    "/density": SlashCommandKind.DENSITY,
    "/compact": SlashCommandKind.DENSITY,
    "/dense": SlashCommandKind.DENSITY,
}


def parse_input(raw: str) -> ParsedCommand:
    """Parse user input into a structured command.

    Slash commands are resolved by exact prefix matching.
    Dead commands and regular queries are treated as natural language for Mya (§34).
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

        # Unknown / dead slash command — treat as natural language
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


class CommandInfo(BaseModel):
    """Human-facing metadata for a slash command (help + autocomplete) (§52, §53)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    category: str
    args: str = ""
    cost: str = ""  # "low" | "medium" | "high" | "max" | ""

    @property
    def takes_argument(self) -> bool:
        return bool(self.args)


def _build_catalog_from_registry() -> list[CommandInfo]:
    """Dynamically generates the command catalog from the canonical CommandRegistry (§52)."""
    cost_map = {
        ExpectedCost.LOW: "low",
        ExpectedCost.MEDIUM: "medium",
        ExpectedCost.HIGH: "high",
        ExpectedCost.VERY_HIGH: "max",
    }
    catalog: list[CommandInfo] = []
    for defn in COMMAND_REGISTRY.visible_commands():
        category_label = CATEGORY_STYLES.get(defn.category, {}).get("label", defn.category.value)
        catalog.append(
            CommandInfo(
                name=defn.slash_name,
                description=defn.description,
                category=category_label,
                args=defn.args,
                cost=cost_map.get(defn.expected_cost, ""),
            )
        )
    return catalog


# Canonical list of visible commands for help and suggestions
COMMAND_CATALOG: list[CommandInfo] = _build_catalog_from_registry()

# Commands available for autocomplete (only visible canonical commands, no dead commands or aliases)
AVAILABLE_COMMANDS: list[str] = sorted(COMMAND_REGISTRY.visible_slash_names())

_CATALOG_BY_NAME: dict[str, CommandInfo] = {c.name: c for c in COMMAND_CATALOG}


def get_completions(prefix: str) -> list[str]:
    """Return slash commands matching the given prefix for autocomplete (§53)."""
    if not prefix.startswith("/"):
        return []
    return [cmd for cmd in AVAILABLE_COMMANDS if cmd.startswith(prefix.lower())]


def get_command_info(name: str) -> CommandInfo | None:
    """Look up catalog metadata for a slash command."""
    return _CATALOG_BY_NAME.get(name.lower())


def search_commands(prefix: str) -> list[CommandInfo]:
    """Return catalog entries matching a typed prefix (prefix first, then substring)."""
    if not prefix.startswith("/"):
        return []
    query = prefix.lower()
    starts = [c for c in COMMAND_CATALOG if c.name.startswith(query)]
    contains = [
        c
        for c in COMMAND_CATALOG
        if c not in starts and (query[1:] in c.name or query[1:] in c.description.lower())
    ]
    return starts + contains if len(query) > 1 else list(COMMAND_CATALOG)
