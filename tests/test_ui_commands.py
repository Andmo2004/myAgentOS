"""Tests for UI slash command parsing."""

from myagentos.ui.commands import (
    AVAILABLE_COMMANDS,
    SlashCommandKind,
    get_completions,
    parse_input,
)


class TestParseInput:
    """Tests for the parse_input function."""

    def test_empty_input(self) -> None:
        cmd = parse_input("")
        assert cmd.kind == SlashCommandKind.NATURAL
        assert cmd.argument == ""

    def test_whitespace_only(self) -> None:
        cmd = parse_input("   ")
        assert cmd.kind == SlashCommandKind.NATURAL

    def test_help_command(self) -> None:
        cmd = parse_input("/help")
        assert cmd.kind == SlashCommandKind.HELP
        assert cmd.argument == ""

    def test_exit_command(self) -> None:
        cmd = parse_input("/exit")
        assert cmd.kind == SlashCommandKind.EXIT

    def test_quit_alias(self) -> None:
        cmd = parse_input("/quit")
        assert cmd.kind == SlashCommandKind.EXIT

    def test_status_command(self) -> None:
        cmd = parse_input("/status")
        assert cmd.kind == SlashCommandKind.STATUS

    def test_dead_commands_become_natural(self) -> None:
        """Dead commands removed in cleanup (§34) must fallback to natural language."""
        for dead_cmd in (
            "/jobs",
            "/job 123",
            "/diff",
            "/log",
            "/cancel",
            "/approve",
            "/reject",
            "/debug",
            "/usage",
            "/audit",
            "/verify",
            "/tests",
            "/settings",
        ):
            cmd = parse_input(dead_cmd)
            assert cmd.kind == SlashCommandKind.NATURAL

    def test_mya_command_with_prompt(self) -> None:
        cmd = parse_input("/mya añade autenticación con GitHub")
        assert cmd.kind == SlashCommandKind.MYA
        assert cmd.argument == "añade autenticación con GitHub"

    def test_mya_command_without_prompt(self) -> None:
        cmd = parse_input("/mya")
        assert cmd.kind == SlashCommandKind.MYA
        assert cmd.argument == ""

    def test_natural_language(self) -> None:
        cmd = parse_input("arregla los tests que están fallando")
        assert cmd.kind == SlashCommandKind.NATURAL
        assert cmd.argument == "arregla los tests que están fallando"

    def test_unknown_slash_command_becomes_natural(self) -> None:
        cmd = parse_input("/unknown something")
        assert cmd.kind == SlashCommandKind.NATURAL

    def test_case_insensitive_commands(self) -> None:
        cmd = parse_input("/HELP")
        assert cmd.kind == SlashCommandKind.HELP

    def test_key_command(self) -> None:
        cmd = parse_input("/key openai sk-test123")
        assert cmd.kind == SlashCommandKind.KEY
        assert cmd.argument == "openai sk-test123"

    def test_keys_alias(self) -> None:
        cmd = parse_input("/keys")
        assert cmd.kind == SlashCommandKind.KEY
        assert cmd.argument == ""

    def test_model_command(self) -> None:
        cmd = parse_input("/model gpt-4o")
        assert cmd.kind == SlashCommandKind.MODEL
        assert cmd.argument == "gpt-4o"

    def test_memory_command(self) -> None:
        cmd = parse_input("/memory search postgres")
        assert cmd.kind == SlashCommandKind.MEMORY
        assert cmd.argument == "search postgres"

    def test_skills_command(self) -> None:
        cmd = parse_input("/skills search python")
        assert cmd.kind == SlashCommandKind.SKILLS
        assert cmd.argument == "search python"

    def test_clear_command(self) -> None:
        cmd = parse_input("/clear")
        assert cmd.kind == SlashCommandKind.CLEAR

    def test_categorize_command(self) -> None:
        cmd = parse_input("/categorize")
        assert cmd.kind == SlashCommandKind.CATEGORIZE

    def test_visual_presentation_commands(self) -> None:
        cmd_th = parse_input("/theme minimal")
        assert cmd_th.kind == SlashCommandKind.THEME
        assert cmd_th.argument == "minimal"

        cmd_mo = parse_input("/motion reduced")
        assert cmd_mo.kind == SlashCommandKind.MOTION
        assert cmd_mo.argument == "reduced"

        cmd_av = parse_input("/avatar ascii")
        assert cmd_av.kind == SlashCommandKind.AVATAR
        assert cmd_av.argument == "ascii"

        cmd_cp = parse_input("/compact")
        assert cmd_cp.kind == SlashCommandKind.COMPACT

        cmd_ds = parse_input("/dense")
        assert cmd_ds.kind == SlashCommandKind.DENSE


class TestAutocomplete:
    """Tests for slash command autocomplete."""

    def test_complete_sta(self) -> None:
        results = get_completions("/sta")
        assert "/status" in results

    def test_complete_m(self) -> None:
        results = get_completions("/m")
        assert "/mya" in results
        assert "/model" in results

    def test_complete_no_slash(self) -> None:
        results = get_completions("hel")
        assert results == []

    def test_complete_full_match(self) -> None:
        results = get_completions("/help")
        assert "/help" in results

    def test_available_commands_sorted(self) -> None:
        assert AVAILABLE_COMMANDS == sorted(AVAILABLE_COMMANDS)
