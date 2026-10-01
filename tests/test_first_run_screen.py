"""Integration tests for FirstRunScreen wizard (§5-§8, §13)."""

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, RadioButton, RadioSet, Static

from myagentos.config.loader import load_config
from myagentos.setup.models import SetupConfig
from myagentos.ui.screens.first_run import FirstRunScreen
from myagentos.ui.theme.themes import ThemeRegistry


@pytest.fixture(autouse=True)
def restore_default_theme() -> None:
    yield
    ThemeRegistry.get_instance().set_active_theme("default")


class FirstRunTestApp(App[SetupConfig | None]):
    """Test app host for FirstRunScreen."""

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self.push_screen(FirstRunScreen(), self._on_screen_dismissed)

    def _on_screen_dismissed(self, result: SetupConfig | None) -> None:
        self.result = result


@pytest.mark.asyncio
async def test_first_run_screen_flow(tmp_path: Path) -> None:
    test_home = tmp_path / "custom_mya_home"
    app = FirstRunTestApp()

    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()

        # Step 1: User display name
        inp_name = pilot.app.screen.query_one("#input_display_name", Input)
        inp_name.value = "Alice"
        btn_s1_next = pilot.app.screen.query_one("#btn_step1_next", Button)
        await pilot.click(btn_s1_next)
        await pilot.pause()

        # Step 2: Theme selection
        radioset = pilot.app.screen.query_one("#radioset_theme", RadioSet)
        assert radioset is not None

        # Check preview
        preview_static = pilot.app.screen.query_one("#preview_theme_static", Static)
        assert "● Mya" in str(preview_static.render())

        # Select minimal theme
        btn_minimal = pilot.app.screen.query_one("#theme_minimal", RadioButton)
        btn_minimal.value = True
        await pilot.pause()

        btn_s2_next = pilot.app.screen.query_one("#btn_step2_next", Button)
        await pilot.click(btn_s2_next)
        await pilot.pause()

        # Step 3: Mya Home
        inp_home = pilot.app.screen.query_one("#input_mya_home", Input)
        inp_home.value = str(test_home)

        btn_s3_next = pilot.app.screen.query_one("#btn_step3_next", Button)
        await pilot.click(btn_s3_next)
        await pilot.pause()

        # Review Step
        btn_confirm = pilot.app.screen.query_one("#btn_confirm_setup", Button)
        await pilot.click(btn_confirm)
        await pilot.pause()

    # Verify result
    assert app.result is not None
    assert app.result.setup_completed is True
    assert app.result.user.display_name == "Alice"
    assert app.result.ui.theme == "minimal"
    assert app.result.mya.home == str(test_home)

    # Verify directory structure and configuration persisted to disk
    assert test_home.is_dir()
    assert (test_home / "version.json").is_file()
    assert (test_home / "config" / "settings.yaml").is_file()
    assert (test_home / "sessions").is_dir()
    assert (test_home / "projects" / "registry").is_dir()

    saved_config = load_config(mya_home=test_home)
    assert saved_config is not None
    assert saved_config.setup.completed is True
    assert saved_config.user.display_name == "Alice"
    assert saved_config.ui.theme == "minimal"


@pytest.mark.asyncio
async def test_first_run_screen_invalid_home_validation(tmp_path: Path) -> None:
    app = FirstRunTestApp()

    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()

        # Step 1 -> Next
        await pilot.click("#btn_step1_next")
        await pilot.pause()

        # Step 2 -> Next
        await pilot.click("#btn_step2_next")
        await pilot.pause()

        # Step 3: Empty Mya Home
        inp_home = pilot.app.screen.query_one("#input_mya_home", Input)
        inp_home.value = "   "
        await pilot.click("#btn_step3_next")
        await pilot.pause()

        error_label = pilot.app.screen.query_one("#label_home_error")
        assert "empty" in str(error_label.render()).lower()

        # Click Usar default
        await pilot.click("#btn_use_default")
        await pilot.pause()
        assert "agenticos" in inp_home.value
