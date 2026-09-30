"""Canonical command metadata catalog and versioning for Mya Commands.

Follows §3, §18 of docs/agentic-os-feature-mya-commands.md.
"""

from __future__ import annotations

from myagentos.mya.commands.models import (
    CommandCategory,
    CommandDefinition,
    ExpectedCost,
)

_BUILTIN_COMMANDS: list[CommandDefinition] = [
    # 1. UI / Observability
    CommandDefinition(
        name="info",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Muestra estado de sesión, presupuesto y consumo de tokens por agente",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
    ),
    CommandDefinition(
        name="telemetry",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Muestra actividad, llamadas y consumo de tokens de agentes",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
    ),
    CommandDefinition(
        name="monitor",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Monitorización en vivo de agentes activos y archivos en scope",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
    ),
    CommandDefinition(
        name="key",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Muestra o configura las claves API (OpenAI, Gemini) y guarda en .env",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
    ),
    CommandDefinition(
        name="model",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Muestra o cambia el modelo LLM activo para Mya",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
    ),
    # 2. Working Modes
    CommandDefinition(
        name="fast",
        version="1.0.0",
        category=CommandCategory.WORKING_MODE,
        description="Ejecución rápida con mínimo overhead sin relajar controles de seguridad",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
        routing_hint="DIRECT_WORKER_CODE",
    ),
    CommandDefinition(
        name="sci_mode",
        version="1.0.0",
        category=CommandCategory.WORKING_MODE,
        description="Modo científico estructurado (hipótesis, método, evidencia, limitaciones)",
        expected_cost=ExpectedCost.MEDIUM,
        supports_arguments=True,
        routing_hint="SCI_MODE",
    ),
    # 3. Research & Analysis
    CommandDefinition(
        name="deep_research",
        version="1.0.0",
        category=CommandCategory.RESEARCH_ANALYSIS,
        description="Investigación exhaustiva en web y papers sin modificar código por defecto",
        expected_cost=ExpectedCost.VERY_HIGH,
        supports_arguments=True,
        routing_hint="DEEP_RESEARCH",
    ),
    CommandDefinition(
        name="optimize",
        version="1.0.0",
        category=CommandCategory.RESEARCH_ANALYSIS,
        description="Análisis de cuellos de botella y propuestas de eficiencia sin mutar código",
        expected_cost=ExpectedCost.MEDIUM,
        supports_arguments=True,
        routing_hint="OPTIMIZE",
    ),
    # 4. Decision & Specialized Expertise
    CommandDefinition(
        name="decision",
        version="1.0.0",
        category=CommandCategory.DECISION_EXPERTISE,
        description="Reúne 5 perspectivas independientes y mapea consensos y discrepancias",
        expected_cost=ExpectedCost.HIGH,
        supports_arguments=True,
        routing_hint="DECISION",
    ),
    CommandDefinition(
        name="cloud",
        version="1.0.0",
        category=CommandCategory.DECISION_EXPERTISE,
        description="Especialización contextual en infraestructura cloud y políticas IAM",
        expected_cost=ExpectedCost.MEDIUM,
        supports_arguments=True,
        routing_hint="CLOUD",
    ),
    CommandDefinition(
        name="security",
        version="1.0.0",
        category=CommandCategory.DECISION_EXPERTISE,
        description="Auditoría especializada de ciberseguridad y riesgos de aplicación OWASP",
        expected_cost=ExpectedCost.MEDIUM,
        supports_arguments=True,
        routing_hint="SECURITY",
    ),
    # Visual & Character presentation commands (§24)
    CommandDefinition(
        name="theme",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Cambia o consulta el tema visual de la interfaz terminal",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
    ),
    CommandDefinition(
        name="motion",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Configura el nivel de animación (full, reduced, off)",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
    ),
    CommandDefinition(
        name="avatar",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Selecciona la representación visual de Mya (dot, glyph, ascii, minimal)",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=True,
    ),
    CommandDefinition(
        name="compact",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Ajusta la densidad visual a modo compacto",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
    ),
    CommandDefinition(
        name="dense",
        version="1.0.0",
        category=CommandCategory.UI_OBSERVABILITY,
        description="Ajusta la densidad visual a modo cómodo",
        expected_cost=ExpectedCost.LOW,
        supports_arguments=False,
    ),
]


class CommandRegistry:
    """Registry providing lookup, versioning, and validation for Mya Commands (§18)."""

    def __init__(self, commands: list[CommandDefinition] | None = None) -> None:
        self._commands: dict[str, CommandDefinition] = {}
        for c in commands or _BUILTIN_COMMANDS:
            self._commands[c.name.lower()] = c

    def get(self, name_or_slash: str) -> CommandDefinition | None:
        key = name_or_slash.strip().lower().lstrip("/")
        return self._commands.get(key)

    def list_all(self) -> list[CommandDefinition]:
        return sorted(self._commands.values(), key=lambda c: (c.category.value, c.name))

    def list_by_category(self, category: CommandCategory) -> list[CommandDefinition]:
        return [c for c in self._commands.values() if c.category == category]

    def get_expected_cost(self, name_or_slash: str) -> ExpectedCost | None:
        defn = self.get(name_or_slash)
        return defn.expected_cost if defn else None


# Canonical shared instance
COMMAND_REGISTRY = CommandRegistry()
