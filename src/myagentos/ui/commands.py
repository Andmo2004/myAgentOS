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
    KEY = "key"
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

    # Visual & Character commands (§24)
    THEME = "theme"
    MOTION = "motion"
    AVATAR = "avatar"
    COMPACT = "compact"
    DENSE = "dense"

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
    "/key": SlashCommandKind.KEY,
    "/keys": SlashCommandKind.KEY,
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
    # Visual & Character Commands
    "/theme": SlashCommandKind.THEME,
    "/motion": SlashCommandKind.MOTION,
    "/avatar": SlashCommandKind.AVATAR,
    "/compact": SlashCommandKind.COMPACT,
    "/dense": SlashCommandKind.DENSE,
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


class CommandInfo(BaseModel):
    """Human-facing metadata for a slash command (help + autocomplete)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    category: str
    args: str = ""
    cost: str = ""  # "low" | "medium" | "high" | "max" | ""

    @property
    def takes_argument(self) -> bool:
        return bool(self.args)


COMMAND_CATALOG: list[CommandInfo] = [
    CommandInfo(name="/help", description="Ver todos los comandos", category="General"),
    CommandInfo(name="/clear", description="Limpiar la conversación", category="General"),
    CommandInfo(name="/status", description="Estado de git y del proyecto", category="General"),
    CommandInfo(name="/projects", description="Abrir explorador de proyectos", category="General"),
    CommandInfo(
        name="/categorize", description="Analizar el perfil del proyecto", category="General"
    ),
    CommandInfo(
        name="/mya", args="<prompt>", description="Hablar directamente con Mya", category="General"
    ),
    CommandInfo(name="/exit", description="Salir de Mya", category="General"),
    CommandInfo(
        name="/info",
        description="Sesión y presupuesto de tokens",
        category="Observabilidad",
        cost="low",
    ),
    CommandInfo(
        name="/telemetry",
        description="Actividad de agentes y uso",
        category="Observabilidad",
        cost="low",
    ),
    CommandInfo(
        name="/monitor",
        description="Estado en vivo de agentes y archivos",
        category="Observabilidad",
        cost="low",
    ),
    CommandInfo(
        name="/fast",
        args="<prompt>",
        description="Ruta rápida, bajo coste",
        category="Modos de trabajo",
        cost="low",
    ),
    CommandInfo(
        name="/sci_mode",
        args="<prompt>",
        description="Análisis científico",
        category="Modos de trabajo",
        cost="medium",
    ),
    CommandInfo(
        name="/deep_research",
        args="<consulta>",
        description="Investigación exhaustiva (sin cambios de código)",
        category="Modos de trabajo",
        cost="max",
    ),
    CommandInfo(
        name="/optimize",
        args="<objetivo>",
        description="Revisión de rendimiento (sin cambios automáticos)",
        category="Modos de trabajo",
        cost="medium",
    ),
    CommandInfo(
        name="/decision",
        args="<pregunta>",
        description="5 perspectivas independientes",
        category="Decisión y expertise",
        cost="high",
    ),
    CommandInfo(
        name="/cloud",
        args="<prompt>",
        description="Arquitectura cloud e IAM",
        category="Decisión y expertise",
        cost="medium",
    ),
    CommandInfo(
        name="/security",
        args="<prompt>",
        description="Auditoría de seguridad y OWASP",
        category="Decisión y expertise",
        cost="medium",
    ),
    CommandInfo(
        name="/theme",
        args="[nombre]",
        description="Tema: default, minimal, high_contrast, monochrome",
        category="Apariencia",
    ),
    CommandInfo(
        name="/motion",
        args="[modo]",
        description="Animación: full, reduced, off",
        category="Apariencia",
    ),
    CommandInfo(
        name="/avatar",
        args="[modo]",
        description="Avatar: dot, glyph, ascii, minimal",
        category="Apariencia",
    ),
    CommandInfo(name="/compact", description="Vista compacta", category="Apariencia"),
    CommandInfo(name="/dense", description="Vista cómoda (espaciada)", category="Apariencia"),
    CommandInfo(
        name="/key",
        args="[proveedor] [clave]",
        description="Conectar un modelo (claude, openai, gemini)",
        category="Configuración",
        cost="low",
    ),
    CommandInfo(
        name="/model",
        args="[nombre]",
        description="Cambiar el modelo activo",
        category="Configuración",
        cost="low",
    ),
]

_CATALOG_BY_NAME: dict[str, CommandInfo] = {c.name: c for c in COMMAND_CATALOG}


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
