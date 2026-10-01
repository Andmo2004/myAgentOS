"""Canonical unified command metadata catalog and versioning for Mya Commands.

Follows §3, §18 of docs/agentic-os-feature-mya-commands.md
and §31-§56, §74-§77 of docs/new_features/agentic-os-feature-skills.md.
"""

from __future__ import annotations

from collections.abc import Callable

from myagentos.mya.commands.models import (
    CommandCategory,
    CommandDefinition,
    ExpectedCost,
)

_BUILTIN_COMMANDS: list[CommandDefinition] = [
    # ── 1. Navigation & System ──────────────────────────────────────
    CommandDefinition(
        name="help",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Ver todos los comandos disponibles",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.help",
    ),
    CommandDefinition(
        name="status",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Estado de git y del proyecto actual",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.status",
    ),
    CommandDefinition(
        name="projects",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Abrir explorador y selector de proyectos",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.projects",
    ),
    CommandDefinition(
        name="memory",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Explorar y buscar en la memoria de proyecto y usuario",
        expected_cost=ExpectedCost.LOW,
        args="[search <término>]",
        supports_arguments=True,
        handler="ui.memory",
    ),
    CommandDefinition(
        name="skills",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Listar e inspeccionar capacidades (skills) disponibles",
        expected_cost=ExpectedCost.LOW,
        args="[search <término>]",
        supports_arguments=True,
        handler="ui.skills",
    ),
    CommandDefinition(
        name="info",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Muestra estado de sesión, presupuesto y consumo de tokens",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.info",
    ),
    CommandDefinition(
        name="telemetry",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Muestra actividad, llamadas y consumo de tokens de agentes",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.telemetry",
    ),
    CommandDefinition(
        name="monitor",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Monitorización en vivo de agentes activos y archivos en scope",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.monitor",
    ),
    CommandDefinition(
        name="clear",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Limpiar la conversación actual",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.clear",
    ),
    CommandDefinition(
        name="exit",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Salir de la interfaz interactiva de Mya",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        aliases=("quit",),
        handler="ui.exit",
    ),
    CommandDefinition(
        name="mya",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Hablar directamente con Mya",
        expected_cost=ExpectedCost.LOW,
        args="<prompt>",
        supports_arguments=True,
        handler="ui.mya",
    ),
    # ── 2. Workflow ─────────────────────────────────────────────────
    CommandDefinition(
        name="fast",
        version="1.0.0",
        category=CommandCategory.WORKFLOW,
        description="Ejecución rápida con mínimo overhead sin relajar controles",
        expected_cost=ExpectedCost.LOW,
        args="<prompt>",
        supports_arguments=True,
        routing_hint="DIRECT_WORKER_CODE",
        handler="mya.fast",
    ),
    CommandDefinition(
        name="science",
        version="1.0.0",
        category=CommandCategory.WORKFLOW,
        description="Modo científico estructurado (hipótesis, método, evidencia)",
        expected_cost=ExpectedCost.MEDIUM,
        args="<prompt>",
        supports_arguments=True,
        routing_hint="SCI_MODE",
        aliases=("sci_mode",),
        handler="mya.science",
    ),
    CommandDefinition(
        name="security",
        version="1.0.0",
        category=CommandCategory.DECISION_EXPERTISE,
        description="Auditoría especializada de ciberseguridad y riesgos OWASP",
        expected_cost=ExpectedCost.MEDIUM,
        args="<prompt>",
        supports_arguments=True,
        routing_hint="SECURITY",
        handler="mya.security",
    ),
    CommandDefinition(
        name="decision",
        version="1.0.0",
        category=CommandCategory.DECISION_EXPERTISE,
        description="Reúne 5 perspectivas independientes y mapea consensos",
        expected_cost=ExpectedCost.HIGH,
        args="<pregunta>",
        supports_arguments=True,
        routing_hint="DECISION",
        handler="mya.decision",
    ),
    # ── 3. Research ─────────────────────────────────────────────────
    CommandDefinition(
        name="deep-research",
        version="1.0.0",
        category=CommandCategory.RESEARCH,
        description="Investigación exhaustiva en web y papers sin modificar código",
        expected_cost=ExpectedCost.VERY_HIGH,
        args="<consulta>",
        supports_arguments=True,
        routing_hint="DEEP_RESEARCH",
        aliases=("deep_research",),
        handler="mya.deep_research",
    ),
    CommandDefinition(
        name="optimize",
        version="1.0.0",
        category=CommandCategory.RESEARCH,
        description="Análisis de cuellos de botella y rendimiento sin mutar código",
        expected_cost=ExpectedCost.MEDIUM,
        args="<objetivo>",
        supports_arguments=True,
        routing_hint="OPTIMIZE",
        handler="mya.optimize",
    ),
    CommandDefinition(
        name="cloud",
        version="1.0.0",
        category=CommandCategory.DECISION_EXPERTISE,
        description="Especialización contextual en arquitectura cloud e IAM",
        expected_cost=ExpectedCost.MEDIUM,
        args="<prompt>",
        supports_arguments=True,
        routing_hint="CLOUD",
        handler="mya.cloud",
    ),
    # ── 4. Configuration ────────────────────────────────────────────
    CommandDefinition(
        name="key",
        version="1.0.0",
        category=CommandCategory.CONFIGURATION,
        description="Muestra o configura las claves API y guarda en .env",
        expected_cost=ExpectedCost.LOW,
        args="[proveedor] [clave]",
        supports_arguments=True,
        aliases=("keys",),
        handler="ui.key",
    ),
    CommandDefinition(
        name="model",
        version="1.0.0",
        category=CommandCategory.CONFIGURATION,
        description="Muestra o cambia el modelo LLM activo para Mya",
        expected_cost=ExpectedCost.LOW,
        args="[nombre]",
        supports_arguments=True,
        handler="ui.model",
    ),
    CommandDefinition(
        name="categorize",
        version="1.0.0",
        category=CommandCategory.CONFIGURATION,
        description="Analizar y clasificar el perfil tecnológico del proyecto",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        handler="ui.categorize",
    ),
    CommandDefinition(
        name="init",
        version="1.0.0",
        category=CommandCategory.CONFIGURATION,
        description="Inicializar o resetear estructura y memoria de Mya en el proyecto (MYA.md, skills, notas)",
        expected_cost=ExpectedCost.LOW,
        args="[reset|force]",
        supports_arguments=True,
        handler="ui.init",
    ),
    # ── 5. Appearance ───────────────────────────────────────────────
    CommandDefinition(
        name="theme",
        version="1.0.0",
        category=CommandCategory.APPEARANCE,
        description="Tema visual: default, minimal, high_contrast, monochrome",
        expected_cost=ExpectedCost.LOW,
        args="[nombre]",
        supports_arguments=True,
        handler="ui.theme",
    ),
    CommandDefinition(
        name="motion",
        version="1.0.0",
        category=CommandCategory.APPEARANCE,
        description="Configura el nivel de animación (full, reduced, off)",
        expected_cost=ExpectedCost.LOW,
        args="[modo]",
        supports_arguments=True,
        handler="ui.motion",
    ),
    CommandDefinition(
        name="avatar",
        version="1.0.0",
        category=CommandCategory.APPEARANCE,
        description="Selecciona la representación visual de Mya (dot, glyph, ascii, minimal)",
        expected_cost=ExpectedCost.LOW,
        args="[modo]",
        supports_arguments=True,
        handler="ui.avatar",
    ),
    CommandDefinition(
        name="density",
        version="1.0.0",
        category=CommandCategory.APPEARANCE,
        description="Ajusta la densidad visual de la interfaz (compact, comfortable)",
        expected_cost=ExpectedCost.LOW,
        args="[modo]",
        supports_arguments=True,
        aliases=("compact", "dense"),
        handler="ui.density",
    ),
    # ── Deprecated Aliases (Hidden) ──────────────────────────────────
    CommandDefinition(
        name="sci_mode",
        version="1.0.0",
        category=CommandCategory.WORKFLOW,
        description="Alias deprecated de /science",
        expected_cost=ExpectedCost.MEDIUM,
        args="<prompt>",
        supports_arguments=True,
        routing_hint="SCI_MODE",
        hidden=True,
        deprecated=True,
        handler="mya.science",
    ),
    CommandDefinition(
        name="deep_research",
        version="1.0.0",
        category=CommandCategory.RESEARCH,
        description="Alias deprecated de /deep-research",
        expected_cost=ExpectedCost.VERY_HIGH,
        args="<consulta>",
        supports_arguments=True,
        routing_hint="DEEP_RESEARCH",
        hidden=True,
        deprecated=True,
        handler="mya.deep_research",
    ),
    CommandDefinition(
        name="compact",
        version="1.0.0",
        category=CommandCategory.APPEARANCE,
        description="Alias deprecated de /density compact",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        hidden=True,
        deprecated=True,
        handler="ui.density",
    ),
    CommandDefinition(
        name="dense",
        version="1.0.0",
        category=CommandCategory.APPEARANCE,
        description="Alias deprecated de /density comfortable",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        hidden=True,
        deprecated=True,
        handler="ui.density",
    ),
    CommandDefinition(
        name="quit",
        version="1.0.0",
        category=CommandCategory.NAVIGATION_SYSTEM,
        description="Alias deprecated de /exit",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
        hidden=True,
        deprecated=True,
        handler="ui.exit",
    ),
    CommandDefinition(
        name="keys",
        version="1.0.0",
        category=CommandCategory.CONFIGURATION,
        description="Alias deprecated de /key",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
        hidden=True,
        deprecated=True,
        handler="ui.key",
    ),
]


class CommandRegistry:
    """Registry providing canonical lookup, versioning, and validation for Mya Commands (§18, §49)."""

    def __init__(self, commands: list[CommandDefinition] | None = None) -> None:
        self._commands: dict[str, CommandDefinition] = {}
        self._alias_map: dict[str, CommandDefinition] = {}
        for c in commands or _BUILTIN_COMMANDS:
            self._commands[c.name.lower()] = c
            for alias in c.aliases:
                self._alias_map[alias.lower()] = c

    def get(self, name_or_slash: str) -> CommandDefinition | None:
        """Lookup command by canonical name or alias (with or without leading slash)."""
        key = name_or_slash.strip().lower().lstrip("/")
        return self._commands.get(key) or self._alias_map.get(key)

    def list_all(self) -> list[CommandDefinition]:
        """Returns all registered command definitions, including deprecated aliases."""
        return sorted(self._commands.values(), key=lambda c: (c.category.value, c.name))

    def visible_commands(self) -> list[CommandDefinition]:
        """Returns only public canonical commands (not hidden or deprecated)."""
        return [
            c
            for c in self.list_all()
            if not c.hidden and not c.deprecated
        ]

    def visible_names(self) -> list[str]:
        """Returns sorted canonical command names without slash."""
        return sorted(c.name for c in self.visible_commands())

    def visible_slash_names(self) -> list[str]:
        """Returns sorted canonical slash command names (e.g. ['/clear', '/exit', ...])."""
        return sorted(c.slash_name for c in self.visible_commands())

    def list_by_category(self, category: CommandCategory) -> list[CommandDefinition]:
        """List visible commands belonging to a given category."""
        return [c for c in self.visible_commands() if c.category == category]

    def get_expected_cost(self, name_or_slash: str) -> ExpectedCost | None:
        defn = self.get(name_or_slash)
        return defn.expected_cost if defn else None

    def search(self, query: str) -> list[CommandDefinition]:
        """Search visible commands matching prefix or query text."""
        q = query.strip().lower().lstrip("/")
        if not q:
            return self.visible_commands()
        starts = [c for c in self.visible_commands() if c.name.startswith(q)]
        contains = [
            c
            for c in self.visible_commands()
            if c not in starts and (q in c.name or q in c.description.lower())
        ]
        return starts + contains

    def validate_handlers(self, handler_lookup: Callable[[str], bool]) -> list[str]:
        """Validates that each visible command has an associated, existing handler (§51)."""
        missing: list[str] = []
        for cmd in self.visible_commands():
            if not cmd.handler or not handler_lookup(cmd.handler):
                missing.append(cmd.name)
        return missing


# Canonical shared instance
COMMAND_REGISTRY = CommandRegistry()
