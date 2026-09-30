"""Domain models, cost indicators, and category styles for Mya Commands.

Follows §3, §7, §8, §9, §18 of docs/agentic-os-feature-mya-commands.md.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CommandCategory(StrEnum):
    """Functional families of Mya Commands (§3)."""

    UI_OBSERVABILITY = "ui_observability"
    WORKING_MODE = "working_mode"
    RESEARCH_ANALYSIS = "research_analysis"
    DECISION_EXPERTISE = "decision_expertise"


# Category style specifications for terminal rendering
# White text on category background pill
CATEGORY_STYLES: dict[CommandCategory, dict[str, str]] = {
    CommandCategory.UI_OBSERVABILITY: {
        "bg_color": "#2563EB",  # Rich Blue
        "fg_color": "white",
        "tag": "bold white on #2563EB",
        "label": "UI / Observability",
    },
    CommandCategory.WORKING_MODE: {
        "bg_color": "#059669",  # Emerald Green
        "fg_color": "white",
        "tag": "bold white on #059669",
        "label": "Working Mode",
    },
    CommandCategory.RESEARCH_ANALYSIS: {
        "bg_color": "#7C3AED",  # Purple / Violet
        "fg_color": "white",
        "tag": "bold white on #7C3AED",
        "label": "Research & Analysis",
    },
    CommandCategory.DECISION_EXPERTISE: {
        "bg_color": "#D97706",  # Amber / Dark Orange
        "fg_color": "white",
        "tag": "bold white on #D97706",
        "label": "Decision & Expertise",
    },
}


class ExpectedCost(StrEnum):
    """Relative expected token cost indicator with textual redundancy (§7, §22)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

    @property
    def badge(self) -> str:
        """Returns the accessible badge with icon and explicit text."""
        match self:
            case ExpectedCost.LOW:
                return "🟢 LOW COST"
            case ExpectedCost.MEDIUM:
                return "🟡 MEDIUM COST"
            case ExpectedCost.HIGH:
                return "🟠 HIGH COST"
            case ExpectedCost.VERY_HIGH:
                return "🔴 VERY HIGH COST"

    @property
    def color(self) -> str:
        match self:
            case ExpectedCost.LOW:
                return "green"
            case ExpectedCost.MEDIUM:
                return "yellow"
            case ExpectedCost.HIGH:
                return "dark_orange"
            case ExpectedCost.VERY_HIGH:
                return "red"


class CommandDefinition(BaseModel):
    """Versioned schema and behavioral metadata of a Mya Command (§18)."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str = "1.0.0"
    category: CommandCategory
    description: str
    expected_cost: ExpectedCost
    supports_arguments: bool = False
    routing_hint: str | None = None
    allowed_combinations: list[str] = Field(default_factory=list)
    forbidden_combinations: list[str] = Field(default_factory=list)

    @property
    def slash_name(self) -> str:
        return f"/{self.name}"

    def format_badge(self) -> str:
        """Formats the command with white bold text on its category background color."""
        style = CATEGORY_STYLES[self.category]
        return f"[{style['tag']}] {self.slash_name} [/{style['tag']}]"


class ObservedFileState(StrEnum):
    """Lifecycle status of a file within an active agent's scope (§9.4)."""

    READ = "READ"
    TOUCHED = "TOUCHED"
    MODIFIED = "MODIFIED"
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"


class LiveAgentState(StrEnum):
    """Observability state of an agent in the /monitor view (§9.3)."""

    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    WAITING = "waiting"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class AgentDisplayConfig(BaseModel):
    """Configurable display names for agents (§8.2). Presentation-only."""

    model_config = ConfigDict(frozen=True)

    names: dict[str, str] = Field(
        default_factory=lambda: {
            "planner": "Architect",
            "worker_1": "Builder",
            "worker_2": "Debugger",
            "worker": "Builder",
            "reviewer": "Guardian",
            "mya": "Mya",
            "router": "Navigator",
            "orchestrator": "Orchestrator",
        }
    )

    def get_display_name(self, agent_id: str) -> str:
        key = agent_id.lower().replace("-", "_")
        return self.names.get(key, agent_id.capitalize())


class AgentActivitySnapshot(BaseModel):
    """Activity and resource metrics for a single agent (§8.1, §9.2)."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    display_name: str
    role: str
    state: LiveAgentState = LiveAgentState.IDLE
    current_task: str = ""
    files: dict[str, ObservedFileState] = Field(default_factory=dict)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    elapsed_sec: float = 0.0


def format_command_badge(command: str, category: CommandCategory | None = None) -> str:
    """Format any slash command string with white bold text on a category background."""
    cmd = command.strip().lower()
    if not cmd.startswith("/"):
        cmd = f"/{cmd}"

    # Default category mapping if not explicitly provided
    if category is None:
        from myagentos.mya.commands.registry import COMMAND_REGISTRY

        clean_name = cmd[1:].split()[0]
        defn = COMMAND_REGISTRY.get(clean_name)
        if defn:
            category = defn.category
        else:
            category = CommandCategory.UI_OBSERVABILITY

    style = CATEGORY_STYLES[category]
    return f"[{style['tag']}] {cmd} [/{style['tag']}]"
