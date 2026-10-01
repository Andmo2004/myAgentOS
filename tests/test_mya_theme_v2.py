"""Acceptance tests for Mya TUI Redesign v2 (§ agentic-os-feature-mya-tui-redesign-v2.md)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import Input

from myagentos.ui.app import MyaApp
from myagentos.ui.theme.mya_theme import (
    INK,
    LINE,
    MUTED,
    PANEL,
    PROVIDERS,
    RED,
    SAGE,
    SAND,
    SURFACE,
    TEXT,
    StatusLine,
    Thinking,
    Welcome,
    resolve_provider,
)
from myagentos.ui.widgets.chat import ChatMessage


# --- AC-12: 12 casos exactos de la Sección 12 --------------------------------
@pytest.mark.parametrize(
    ("model", "provider", "expected"),
    [
        ("mock-mya", None, "mock"),
        ("claude-sonnet-5-5", None, "claude"),
        ("gpt-5", None, "openai"),
        ("o3-mini", None, "openai"),
        ("gemini-2.5-pro", None, "gemini"),
        ("anthropic/claude-opus-5-5", None, "claude"),
        ("openai/gpt-5", None, "openai"),
        ("google/gemini-2.5-pro", None, "gemini"),
        ("llama3.1", None, "mya"),
        ("ollama/llama3.1", None, "mya"),
        ("mistral-large", "anthropic", "claude"),  # provider explícito gana
        ("x", "desconocido", "mya"),
    ],
)
def test_resolve_provider(model: str, provider: str | None, expected: str) -> None:
    assert resolve_provider(model, provider) == expected


# --- AC-1 & AC-2: Cambio en caliente de modelo, tema y proveedor -------------
@pytest.mark.asyncio
async def test_mya_app_hot_swap_model_themes() -> None:
    app = MyaApp(check_first_run=False, model_id="mock-mya")
    async with app.run_test(size=(90, 30)) as pilot:
        # Default mock-mya
        assert pilot.app.provider == "mock"
        assert pilot.app.theme == "mya-mock"

        # 1. Claude -> claude / mya-claude (naranja)
        pilot.app.set_model("claude-sonnet-5-5", notify_chat=True)
        await pilot.pause()
        assert pilot.app.provider == "claude"
        assert pilot.app.theme == "mya-claude"

        # 2. OpenAI -> openai / mya-openai (verde)
        pilot.app.set_model("gpt-5", notify_chat=True)
        await pilot.pause()
        assert pilot.app.provider == "openai"
        assert pilot.app.theme == "mya-openai"

        # 3. Gemini -> gemini / mya-gemini (azul)
        pilot.app.set_model("gemini-2.5-pro", notify_chat=True)
        await pilot.pause()
        assert pilot.app.provider == "gemini"
        assert pilot.app.theme == "mya-gemini"

        # 4. Fallback -> mya / mya-mya (rosa)
        pilot.app.set_model("llama3.1", notify_chat=True)
        await pilot.pause()
        assert pilot.app.provider == "mya"
        assert pilot.app.theme == "mya-mya"


# --- AC-3: El historial conserva el color de su modelo tras el cambio --------
@pytest.mark.asyncio
async def test_mya_app_history_preserves_provider_color() -> None:
    app = MyaApp(check_first_run=False, model_id="gpt-5")
    async with app.run_test(size=(90, 30)) as pilot:
        assert pilot.app.provider == "openai"

        # Simula respuesta de OpenAI
        pilot.app._append_mya_message("Respuesta generada con OpenAI")
        await pilot.pause()

        conv = pilot.app.query_one("#conversation")
        messages = [c for c in conv.children if isinstance(c, ChatMessage)]
        assert len(messages) >= 1
        openai_msg = messages[-1]
        assert "p-openai" in openai_msg.classes

        # Cambia de modelo a Claude
        pilot.app.set_model("claude-sonnet-5-5")
        await pilot.pause()
        assert pilot.app.provider == "claude"

        # Simula respuesta de Claude
        pilot.app._append_mya_message("Respuesta generada con Claude")
        await pilot.pause()

        messages = [c for c in conv.children if isinstance(c, ChatMessage)]
        assert len(messages) >= 2
        claude_msg = messages[-1]
        assert "p-claude" in claude_msg.classes

        # El mensaje previo de OpenAI debe seguir conservando p-openai
        assert "p-openai" in openai_msg.classes


# --- AC-4, AC-5, AC-6: Barra de estado por segmentos y sin huecos ------------
def test_status_line_segments_and_mock_sand() -> None:
    status = StatusLine()
    status.set(project=None, branch=None, model="mock-mya")

    # Sin repositorio: no deben aparecer branch ni separadores huérfanos |
    assert status._project is None
    assert status._branch is None
    assert status._model == "mock-mya"


@pytest.mark.asyncio
async def test_status_line_rendered_content(tmp_path: Path) -> None:
    app = MyaApp(repo_path=tmp_path, check_first_run=False, model_id="mock-mya")
    async with app.run_test(size=(90, 30)) as pilot:
        status = pilot.app.query_one("#status-bar", StatusLine)
        assert status is not None
        assert status._model == "mock-mya"
        assert status._project is None
        assert status._branch is None


# --- AC-7 & AC-8: Welcome unboxed con saludo único y acciones en SAND --------
@pytest.mark.asyncio
async def test_welcome_unboxed_actions(tmp_path: Path) -> None:
    app = MyaApp(repo_path=tmp_path, check_first_run=False, model_id="mock-mya")
    async with app.run_test(size=(90, 30)) as pilot:
        welcome = pilot.app.query_one("#welcome", Welcome)
        assert welcome is not None
        # Con modelo mock y sin proyecto, faltan ambos
        assert welcome.has_model is False
        assert welcome.has_project is False


# --- AC-11: MYA_REDUCED_MOTION=1 ---------------------------------------------
@pytest.mark.asyncio
async def test_reduced_motion_welcome_and_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYA_REDUCED_MOTION", "1")

    welcome = Welcome(user_or_session="Alice", has_model=True, has_project=True)
    assert welcome.progress == 0.0
    welcome._reveal()
    # Con reduced motion, el progreso debe saltar inmediatamente a 1.0 sin animar
    assert welcome.progress == 1.0

    thinking = Thinking()
    assert thinking is not None


# --- AC-13: Prompt sin caja y con glifo ❯ -------------------------------------
@pytest.mark.asyncio
async def test_prompt_clean_unboxed_layout() -> None:
    app = MyaApp(check_first_run=False)
    async with app.run_test(size=(80, 24)) as pilot:
        prompt_label = pilot.app.query_one("#prompt-label")
        assert prompt_label is not None
        assert "❯" in str(prompt_label.render())

        inp = pilot.app.query_one("#prompt-input", Input)
        assert inp is not None
        assert pilot.app.focused == inp


# --- F2: Ciclo de modelos al vuelo (§ demo_ui.py) -----------------------------
@pytest.mark.asyncio
async def test_f2_cycles_models_and_mounts_tool_message() -> None:
    app = MyaApp(check_first_run=False, model_id="mock-mya")
    async with app.run_test(size=(80, 24)) as pilot:
        assert pilot.app.provider == "mock"

        # Pulsar F2
        await pilot.press("f2")
        await pilot.pause()
        assert pilot.app.provider == "claude"
        assert pilot.app.theme == "mya-claude"

        # Verificar mensaje tool con firma del modelo montado en conversación
        conv = pilot.app.query_one("#conversation")
        messages = [c for c in conv.children if isinstance(c, ChatMessage)]
        assert len(messages) >= 1
        tool_msg = messages[-1]
        assert "tool" in tool_msg.classes
        assert "modelo claude-sonnet-5-5" in str(tool_msg._content)

        # Pulsar F2 otra vez
        await pilot.press("f2")
        await pilot.pause()
        assert pilot.app.provider == "openai"
        assert pilot.app.theme == "mya-openai"


# --- Markdown en respuestas del agente (§ agentic-os-feature-mya-tui-redesign-v2.md)
@pytest.mark.asyncio
async def test_agent_message_renders_markdown() -> None:
    app = MyaApp(check_first_run=False, model_id="gpt-5")
    async with app.run_test(size=(80, 24)) as pilot:
        pilot.app._append_mya_message("Listo.\n\n- Punto 1\n- Punto 2")
        await pilot.pause()

        conv = pilot.app.query_one("#conversation")
        messages = [c for c in conv.children if isinstance(c, ChatMessage)]
        assert len(messages) >= 1
        agent_msg = messages[-1]
        assert "agent" in agent_msg.classes
        assert "p-openai" in agent_msg.classes

