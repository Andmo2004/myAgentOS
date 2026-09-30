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
