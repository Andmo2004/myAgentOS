"""Tests for Mya interactive terminal UI (headless Textual app)."""

import pytest
from textual.widgets import Input

from myagentos.ui.app import MyaApp


@pytest.mark.asyncio
async def test_mya_app_startup_and_welcome() -> None:
    app = MyaApp()
    async with app.run_test() as pilot:
        assert pilot.app.title == "Mya · Agentic OS"
        # Verify widgets are mounted
        assert pilot.app.query_one("#welcome") is not None
        assert pilot.app.query_one("#conversation") is not None
        assert pilot.app.query_one("#prompt-input") is not None


@pytest.mark.asyncio
async def test_mya_app_handle_greeting() -> None:
    app = MyaApp()
    async with app.run_test() as pilot:
        # Simulate typing greeting
        inp = pilot.app.query_one("#prompt-input", Input)
        inp.value = "hola mya"
        await pilot.press("enter")
        await pilot.pause()

        # Check conversation received user message and mya reply
        conversation = pilot.app.query_one("#conversation")
        children = list(conversation.children)
        assert len(children) >= 2


@pytest.mark.asyncio
async def test_mya_app_handle_task_intent() -> None:
    app = MyaApp()
    async with app.run_test() as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)
        inp.value = "arregla los tests de autenticación"
        await pilot.press("enter")
        await pilot.pause()

        conversation = pilot.app.query_one("#conversation")
        children = list(conversation.children)
        assert len(children) >= 2


@pytest.mark.asyncio
async def test_mya_app_slash_status() -> None:
    app = MyaApp()
    async with app.run_test() as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)
        inp.value = "/status"
        await pilot.press("enter")
        await pilot.pause()

        conversation = pilot.app.query_one("#conversation")
        children = list(conversation.children)
        assert len(children) >= 2


@pytest.mark.asyncio
async def test_mya_app_input_interactivity_and_typing() -> None:
    """Verify that keyboard strokes actually reach prompt input without manual value setting."""
    app = MyaApp()
    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)
        assert pilot.app.focused == inp
        assert inp.has_focus

        # Type character by character via pilot keyboard events
        for char in "hola mya":
            await pilot.press(char)
        await pilot.pause()
        assert inp.value == "hola mya"

        # Press enter to submit
        await pilot.press("enter")
        await pilot.pause()
        assert inp.value == ""  # Cleared after submit

        conversation = pilot.app.query_one("#conversation")
        assert len(list(conversation.children)) >= 2


@pytest.mark.asyncio
async def test_mya_app_click_focus_and_retention() -> None:
    """Verify clicking various areas preserves or gives focus to prompt input."""
    app = MyaApp()
    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)

        # Click prompt label and check focus
        await pilot.click("#prompt-label")
        assert pilot.app.focused == inp

        # Click prompt container and check focus
        await pilot.click("#prompt-container")
        assert pilot.app.focused == inp

        # Click status bar and check focus
        await pilot.click("#status-bar")
        assert pilot.app.focused == inp

        # Click conversation area: should not steal focus away from input
        await pilot.click("#conversation")
        assert pilot.app.focused == inp

        # Click welcome banner: should not steal focus away from input
        await pilot.click("#welcome")
        assert pilot.app.focused == inp


@pytest.mark.asyncio
async def test_mya_app_layout_geometry_and_visibility() -> None:
    """Verify prompt input has wide dimensions and is never crushed to width 0."""
    for size in [(80, 24), (100, 30), (120, 40)]:
        app = MyaApp()
        async with app.run_test(size=size) as pilot:
            inp = pilot.app.query_one("#prompt-input", Input)
            assert inp.region.width >= 50
            assert inp.content_region.width >= 40
            assert inp.region.height == 3


@pytest.mark.asyncio
async def test_mya_app_slash_clear() -> None:
    """Verify /clear keeps welcome banner and clears chat messages."""
    app = MyaApp()
    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)
        inp.value = "test message"
        await pilot.press("enter")
        await pilot.pause()

        conversation = pilot.app.query_one("#conversation")
        assert len(list(conversation.children)) >= 2

        inp.value = "/clear"
        await pilot.press("enter")
        await pilot.pause()

        assert pilot.app.query_one("#welcome") is not None
        assert len(list(conversation.children)) == 1
