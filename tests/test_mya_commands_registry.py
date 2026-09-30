from myagentos.mya.commands.models import (
    AgentDisplayConfig,
    ExpectedCost,
    format_command_badge,
)
from myagentos.mya.commands.registry import COMMAND_REGISTRY


def test_command_registry_contains_all_commands():
    core_10_commands = {
        "info",
        "telemetry",
        "monitor",
        "fast",
        "sci_mode",
        "deep_research",
        "optimize",
        "decision",
        "cloud",
        "security",
    }
    all_cmds = COMMAND_REGISTRY.list_all()
    names = {c.name for c in all_cmds}
    assert core_10_commands.issubset(names)
    assert {"theme", "motion", "avatar", "compact", "dense"}.issubset(names)


def test_command_lookup_with_or_without_slash():
    c1 = COMMAND_REGISTRY.get("/fast")
    c2 = COMMAND_REGISTRY.get("fast")
    assert c1 is not None and c2 is not None
    assert c1.name == "fast"
    assert c1.expected_cost == ExpectedCost.LOW
    assert c1.supports_arguments is True
    assert c1.routing_hint == "DIRECT_WORKER_CODE"


def test_expected_cost_badges_have_text_redundancy():
    assert "LOW COST" in ExpectedCost.LOW.badge
    assert "MEDIUM COST" in ExpectedCost.MEDIUM.badge
    assert "HIGH COST" in ExpectedCost.HIGH.badge
    assert "VERY HIGH COST" in ExpectedCost.VERY_HIGH.badge


def test_category_badge_formatting():
    # User's requirement: Colored background pill with white text
    badge_info = format_command_badge("/info")
    assert "bold white on #2563EB" in badge_info
    assert "/info" in badge_info

    badge_fast = format_command_badge("/fast")
    assert "bold white on #059669" in badge_fast
    assert "/fast" in badge_fast

    badge_research = format_command_badge("/deep_research")
    assert "bold white on #7C3AED" in badge_research
    assert "/deep_research" in badge_research

    badge_sec = format_command_badge("/security")
    assert "bold white on #D97706" in badge_sec
    assert "/security" in badge_sec


def test_agent_display_names():
    cfg = AgentDisplayConfig()
    assert cfg.get_display_name("planner") == "Architect"
    assert cfg.get_display_name("worker_1") == "Builder"
    assert cfg.get_display_name("reviewer") == "Guardian"
    assert cfg.get_display_name("worker_2") == "Debugger"
    assert cfg.get_display_name("custom_agent") == "Custom_agent"
