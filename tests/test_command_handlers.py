"""Tests for new and updated command handlers: /density, /memory, /skills (§46, §57)."""

import tempfile
from pathlib import Path

import pytest
from textual.widgets import Input

from myagentos.memory.manager import SharedMemoryManager
from myagentos.ui.app import MyaApp


@pytest.mark.asyncio
async def test_density_command_switches_classes():
    temp_dir = Path(tempfile.mkdtemp())
    app = MyaApp(repo_path=temp_dir)
    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)

        # 1. Switch to compact
        app._fill_prompt("/density compact")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.has_class("-compact")

        # 2. Switch to comfortable
        app._fill_prompt("/density comfortable")
        await pilot.press("enter")
        await pilot.pause()
        assert not app.screen.has_class("-compact")

        # 3. Legacy /compact alias
        app._fill_prompt("/compact")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.has_class("-compact")

        # 4. Legacy /dense alias
        app._fill_prompt("/dense")
        await pilot.press("enter")
        await pilot.pause()
        assert not app.screen.has_class("-compact")


@pytest.mark.asyncio
async def test_memory_command_renders_status_and_search():
    temp_dir = Path(tempfile.mkdtemp())
    memory = SharedMemoryManager(temp_dir / "memory")
    memory.propose_user_memory(user_id="test_user", content="Prefiere respuestas en español")

    app = MyaApp(repo_path=temp_dir)
    app.mya_agent.memory_manager = memory
    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)

        # 1. Status overview
        app._fill_prompt("/memory")
        await pilot.press("enter")
        await pilot.pause()

        # 2. Search query
        app._fill_prompt("/memory search respuestas")
        await pilot.press("enter")
        await pilot.pause()


@pytest.mark.asyncio
async def test_skills_command_renders_catalog_and_search():
    temp_dir = Path(tempfile.mkdtemp())
    app = MyaApp(repo_path=temp_dir)
    async with app.run_test(size=(80, 24)) as pilot:
        inp = pilot.app.query_one("#prompt-input", Input)

        # 1. Skills catalog
        app._fill_prompt("/skills")
        await pilot.press("enter")
        await pilot.pause()

        # 2. Search
        app._fill_prompt("/skills search python")
        await pilot.press("enter")
        await pilot.pause()

        # 3. Show details of a skill JIT
        app._fill_prompt("/skills show cybersecurity")
        await pilot.press("enter")
        await pilot.pause()
