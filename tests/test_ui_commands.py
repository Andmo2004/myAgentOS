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

    def test_jobs_command(self) -> None:
        cmd = parse_input("/jobs")
        assert cmd.kind == SlashCommandKind.JOBS

    def test_job_detail_with_argument(self) -> None:
        cmd = parse_input("/job abc123")
        assert cmd.kind == SlashCommandKind.JOB_DETAIL
        assert cmd.argument == "abc123"

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

    def test_diff_command(self) -> None:
        cmd = parse_input("/diff")
        assert cmd.kind == SlashCommandKind.DIFF

    def test_cancel_command(self) -> None:
        cmd = parse_input("/cancel")
        assert cmd.kind == SlashCommandKind.CANCEL

    def test_approve_command(self) -> None:
        cmd = parse_input("/approve")
        assert cmd.kind == SlashCommandKind.APPROVE

    def test_reject_command(self) -> None:
        cmd = parse_input("/reject")
        assert cmd.kind == SlashCommandKind.REJECT

    def test_debug_command(self) -> None:
        cmd = parse_input("/debug")
        assert cmd.kind == SlashCommandKind.DEBUG

    def test_clear_command(self) -> None:
        cmd = parse_input("/clear")
        assert cmd.kind == SlashCommandKind.CLEAR

    def test_categorize_command(self) -> None:
        cmd = parse_input("/categorize")
        assert cmd.kind == SlashCommandKind.CATEGORIZE


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
