"""Integration test for MyaApp first run integration (§28)."""

from pathlib import Path

import pytest
from textual.widgets import Input

from myagentos.config.loader import save_config
from myagentos.setup.models import (
    MyaHomeConfig,
    SetupConfig,
    SetupMeta,
    UIConfig,
    UserConfig,
)
from myagentos.ui.app import MyaApp, WelcomePanel
from myagentos.ui.screens.first_run import FirstRunScreen
from myagentos.ui.theme.themes import ThemeRegistry


@pytest.fixture(autouse=True)
def restore_default_theme() -> None:
    yield
    ThemeRegistry.get_instance().set_active_theme("default")


@pytest.mark.asyncio
async def test_mya_app_launches_first_run_screen_when_needed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    non_existent_home = tmp_path / "fresh_home"
    monkeypatch.setenv("MYA_HOME", str(non_existent_home))

    app = MyaApp(check_first_run=True)
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        # Verify FirstRunScreen is active
        assert isinstance(pilot.app.screen, FirstRunScreen)


@pytest.mark.asyncio
async def test_mya_app_loads_saved_config_on_normal_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    existing_home = tmp_path / "existing_home"
    monkeypatch.setenv("MYA_HOME", str(existing_home))

    config = SetupConfig(
        setup=SetupMeta(completed=True),
        user=UserConfig(display_name="Elena"),
        ui=UIConfig(theme="minimal"),
        mya=MyaHomeConfig(home=str(existing_home)),
    )
    save_config(config, mya_home=existing_home)

    app = MyaApp(check_first_run=True)
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        # Should not launch FirstRunScreen
        assert not isinstance(pilot.app.screen, FirstRunScreen)
        # Should focus prompt input
        inp = pilot.app.query_one("#prompt-input", Input)
        assert pilot.app.focused == inp
        # WelcomePanel should have Elena
        welcome = pilot.app.query_one("#welcome", WelcomePanel)
        assert welcome.user_name == "Elena"
        assert "Elena" in str(welcome.render())
