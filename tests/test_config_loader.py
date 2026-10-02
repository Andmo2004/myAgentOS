"""Unit tests for config loader and saver (§15)."""

from pathlib import Path

from myagentos.config.loader import load_config, save_config
from myagentos.setup.models import (
    MyaHomeConfig,
    SetupConfig,
    SetupMeta,
    UIConfig,
    UserConfig,
)


def test_load_config_non_existent(tmp_path: Path) -> None:
    non_existent = tmp_path / "settings.yaml"
    assert load_config(path=non_existent) is None


def test_save_and_load_config_roundtrip(tmp_path: Path) -> None:
    settings_file = tmp_path / "config" / "settings.yaml"
    config = SetupConfig(
        schema_version=1,
        setup=SetupMeta(completed=True, completed_at="2026-10-01T12:00:00Z"),
        user=UserConfig(display_name="Tester"),
        ui=UIConfig(theme="minimal", motion="reduced"),
        mya=MyaHomeConfig(home=str(tmp_path)),
    )

    saved_path = save_config(config, path=settings_file)
    assert saved_path == settings_file
    assert settings_file.is_file()

    loaded = load_config(path=settings_file)
    assert loaded is not None
    assert loaded.setup.completed is True
    assert loaded.user.display_name == "Tester"
    assert loaded.ui.theme == "minimal"
    assert loaded.mya.home == str(tmp_path)


def test_load_config_empty_or_invalid_file(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("", encoding="utf-8")
    assert load_config(path=empty_file) is None

    # Truly unparseable YAML syntax error
    invalid_file = tmp_path / "invalid.yaml"
    invalid_file.write_text("unclosed: [item1, item2\n  bad_indent", encoding="utf-8")
    assert load_config(path=invalid_file) is None

    # Non-dictionary YAML (e.g. integer or list)
    scalar_file = tmp_path / "scalar.yaml"
    scalar_file.write_text("42\n", encoding="utf-8")
    assert load_config(path=scalar_file) is None
