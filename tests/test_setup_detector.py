"""Unit tests for first run detector (§4)."""

from pathlib import Path

from myagentos.config.loader import save_config
from myagentos.setup.detector import is_setup_complete, needs_first_run
from myagentos.setup.models import (
    MyaHomeConfig,
    SetupConfig,
    SetupMeta,
    UIConfig,
    UserConfig,
)


def test_needs_first_run_when_no_config(tmp_path: Path) -> None:
    assert needs_first_run(mya_home=tmp_path) is True
    assert is_setup_complete(mya_home=tmp_path) is False


def test_needs_first_run_when_incomplete_config(tmp_path: Path) -> None:
    config = SetupConfig(
        setup=SetupMeta(completed=False),
        user=UserConfig(display_name="Incomplete"),
        ui=UIConfig(),
        mya=MyaHomeConfig(home=str(tmp_path)),
    )
    save_config(config, mya_home=tmp_path)

    assert needs_first_run(mya_home=tmp_path) is True
    assert is_setup_complete(mya_home=tmp_path) is False


def test_setup_complete_when_completed_true(tmp_path: Path) -> None:
    config = SetupConfig(
        setup=SetupMeta(completed=True, completed_at="2026-10-01T00:00:00Z"),
        user=UserConfig(display_name="Complete"),
        ui=UIConfig(),
        mya=MyaHomeConfig(home=str(tmp_path)),
    )
    save_config(config, mya_home=tmp_path)

    assert needs_first_run(mya_home=tmp_path) is False
    assert is_setup_complete(mya_home=tmp_path) is True
