"""Tests for UI theme system, symbols, and micro-animations (§7, §8, §20)."""

import pytest

from myagentos.ui.theme import (
    CostTier,
    FileActivityState,
    ThemeRegistry,
    VisualStatus,
    get_pulse,
    get_spinner,
    get_status_symbol,
    render_progress_bar,
)


def test_standard_symbols_utf8_and_ascii() -> None:
    # Test UTF8 symbols
    assert get_status_symbol(VisualStatus.RUNNING, ascii_only=False) == "●"
    assert get_status_symbol(VisualStatus.SUCCESS, ascii_only=False) == "✓"
    assert get_status_symbol(VisualStatus.FAILED, ascii_only=False) == "×"
    assert get_status_symbol(VisualStatus.WAITING, ascii_only=False) == "…"

    # Test ASCII fallbacks
    assert get_status_symbol(VisualStatus.RUNNING, ascii_only=True) == "(*)"
    assert get_status_symbol(VisualStatus.SUCCESS, ascii_only=True) == "[v]"
    assert get_status_symbol(VisualStatus.FAILED, ascii_only=True) == "[x]"
    assert get_status_symbol(VisualStatus.WAITING, ascii_only=True) == "..."


def test_theme_registry_and_switching() -> None:
    registry = ThemeRegistry.get_instance()
    assert registry.active_theme.name == "default"

    # Switch to minimal
    theme_min = registry.set_active_theme("minimal")
    assert theme_min.name == "minimal"
    assert registry.active_theme.name == "minimal"

    # Switch to monochrome
    theme_mono = registry.set_active_theme("monochrome")
    assert theme_mono.ascii_only is True
    assert theme_mono.get_symbol(VisualStatus.SUCCESS) == "[v]"

    # Switch back to default
    theme_def = registry.set_active_theme("default")
    assert theme_def.ascii_only is False
    assert theme_def.get_symbol(VisualStatus.SUCCESS) == "✓"

    # Invalid theme raises ValueError
    with pytest.raises(ValueError):
        registry.set_active_theme("non_existent_theme")


def test_micro_animations_deterministic() -> None:
    spinner = get_spinner(ascii_only=False)
    frame1 = spinner.current
    frame2 = spinner.advance()
    assert frame1 != frame2

    # Reset
    spinner.reset()
    assert spinner.current == frame1

    # ASCII pulse
    pulse = get_pulse(ascii_only=True)
    assert pulse.current == "(*)"


def test_render_progress_bar() -> None:
    bar_50 = render_progress_bar(0.5, width=10, ascii_only=False)
    assert "50%" in bar_50
    assert "█" in bar_50

    bar_ascii = render_progress_bar(1.0, width=10, ascii_only=True)
    assert "100%" in bar_ascii
    assert "#" in bar_ascii

    # Clamping
    bar_over = render_progress_bar(1.5, width=10)
    assert "100%" in bar_over

    bar_under = render_progress_bar(-0.5, width=10)
    assert "0%" in bar_under


def test_file_activity_and_cost_tokens() -> None:
    assert FileActivityState.READ == "READ"
    assert FileActivityState.TOUCHED == "TOUCHED"
    assert FileActivityState.MODIFIED == "MODIFIED"
    assert FileActivityState.PROPOSED == "PROPOSED"
    assert FileActivityState.VERIFIED == "VERIFIED"

    assert CostTier.LOW == "LOW"
    assert CostTier.VERY_HIGH == "VERY HIGH"
