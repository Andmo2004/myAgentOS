"""Tests for canonical CommandRegistry invariants (§49-§55, §74-§75)."""

from myagentos.mya.commands.models import CommandCategory
from myagentos.mya.commands.registry import COMMAND_REGISTRY
from myagentos.ui.commands import AVAILABLE_COMMANDS, COMMAND_CATALOG


def test_command_registry_canonical_names_unique():
    """Canonical command names must be unique without duplicates (§75)."""
    visible = COMMAND_REGISTRY.visible_commands()
    names = [c.name for c in visible]
    assert len(names) == len(set(names))
    # Approximate target: ~21-25 canonical commands
    assert 20 <= len(names) <= 30


def test_every_visible_command_has_valid_handler():
    """CI Invariant: Every visible command must declare a handler (§51, §75)."""
    valid_handler_prefixes = ("ui.", "mya.")
    for cmd in COMMAND_REGISTRY.visible_commands():
        assert cmd.handler is not None, f"Command {cmd.name} has no handler"
        assert any(cmd.handler.startswith(p) for p in valid_handler_prefixes), (
            f"Command {cmd.name} has invalid handler: {cmd.handler}"
        )

    missing = COMMAND_REGISTRY.validate_handlers(
        lambda h: any(h.startswith(p) for p in valid_handler_prefixes)
    )
    assert missing == []


def test_no_dead_commands_in_registry_or_autocomplete():
    """Dead commands (§34) must not appear in the registry, catalog or autocomplete."""
    dead_commands = {
        "jobs",
        "job",
        "diff",
        "log",
        "cancel",
        "approve",
        "reject",
        "debug",
        "usage",
        "audit",
        "verify",
        "tests",
        "settings",
    }
    visible_names = set(COMMAND_REGISTRY.visible_names())
    assert dead_commands.isdisjoint(visible_names)

    autocomplete_names = {cmd.lstrip("/") for cmd in AVAILABLE_COMMANDS}
    assert dead_commands.isdisjoint(autocomplete_names)

    catalog_names = {info.name.lstrip("/") for info in COMMAND_CATALOG}
    assert dead_commands.isdisjoint(catalog_names)


def test_aliases_resolve_to_canonical_definition():
    """Aliases must resolve to a valid command definition (§50)."""
    alias_expectations = {
        "quit": "exit",
        "keys": "key",
        "sci_mode": "science",
        "deep_research": "deep-research",
        "compact": "density",
        "dense": "density",
    }
    for alias, canonical in alias_expectations.items():
        cmd = COMMAND_REGISTRY.get(alias)
        assert cmd is not None, f"Alias {alias} not found"
        # Resolved either to canonical or points to canonical
        assert cmd.name in (canonical, alias)
        if cmd.name == alias:
            assert cmd.deprecated is True
            assert cmd.hidden is True


def test_help_and_autocomplete_generated_from_registry():
    """Help catalog and autocomplete must be generated directly from registry (§52, §53)."""
    visible_slash = set(COMMAND_REGISTRY.visible_slash_names())
    catalog_slash = {info.name for info in COMMAND_CATALOG}
    autocomplete_slash = set(AVAILABLE_COMMANDS)

    assert visible_slash == catalog_slash
    assert visible_slash == autocomplete_slash


def test_command_registry_categories_distribution():
    """Commands must be categorized according to the simplified 5 families (§54)."""
    categories = {cmd.category for cmd in COMMAND_REGISTRY.visible_commands()}
    # Navigation & System, Workflow, Research, Configuration, Appearance
    assert CommandCategory.NAVIGATION_SYSTEM in categories
    assert CommandCategory.CONFIGURATION in categories
    assert CommandCategory.APPEARANCE in categories


def test_command_search_functionality():
    """Search matches canonical commands by name or description (§48, §57)."""
    results_sci = COMMAND_REGISTRY.search("sci")
    assert any(c.name in ("science", "sci_mode") for c in results_sci)

    results_density = COMMAND_REGISTRY.search("density")
    assert any(c.name == "density" for c in results_density)

    results_memory = COMMAND_REGISTRY.search("memory")
    assert any(c.name == "memory" for c in results_memory)
