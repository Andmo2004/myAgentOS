"""Tests for CLI setup command (§24)."""

from pathlib import Path

import pytest

from myagentos.cli import cmd_setup
from myagentos.config.loader import load_config
from myagentos.setup.detector import is_setup_complete


def test_cli_setup_custom_arguments(tmp_path: Path) -> None:
    custom_home = tmp_path / "cli_mya_home"

    # Run cmd_setup
    cmd_setup(
        name="Bob",
        theme="high_contrast",
        mya_home=str(custom_home),
        non_interactive=True,
    )

    assert custom_home.is_dir()
    assert (custom_home / "version.json").is_file()
    assert (custom_home / "config" / "settings.yaml").is_file()

    config = load_config(mya_home=custom_home)
    assert config is not None
    assert config.setup_completed is True
    assert config.user.display_name == "Bob"
    assert config.ui.theme == "high_contrast"
    assert config.mya.home == str(custom_home)
    assert is_setup_complete(custom_home) is True


def test_cli_setup_already_complete_skip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    custom_home = tmp_path / "already_done"
    cmd_setup(name="Bob", theme="default", mya_home=str(custom_home))

    # Second call without force should skip
    cmd_setup(name="Alice", theme="minimal", mya_home=str(custom_home), force=False)
    captured = capsys.readouterr()
    assert "already completed" in captured.out.lower()

    # Config should still have Bob
    config = load_config(mya_home=custom_home)
    assert config is not None
    assert config.user.display_name == "Bob"

    # Second call with force should update
    cmd_setup(name="Alice", theme="minimal", mya_home=str(custom_home), force=True)
    config = load_config(mya_home=custom_home)
    assert config is not None
    assert config.user.display_name == "Alice"
    assert config.ui.theme == "minimal"


def test_cli_setup_invalid_path(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cmd_setup(name="Bob", mya_home="/System/invalid_mya_home")
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "error" in captured.out.lower() or "protected" in captured.out.lower()


def test_cli_setup_invalid_theme(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target_home = tmp_path / "theme_test"
    with pytest.raises(SystemExit) as exc:
        cmd_setup(name="Bob", theme="non_existent_theme", mya_home=str(target_home))
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "invalid" in captured.out.lower()
