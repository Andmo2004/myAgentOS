"""Tests for Mya presentation semantics and decoupled renderers (§14, §15, §19, §34)."""

from myagentos.mya.presentation import (
    AsciiMyaRenderer,
    DotMyaRenderer,
    GlyphMyaRenderer,
    MinimalMyaRenderer,
    MyaPresentationState,
    MyaRenderer,
    MyaRenderState,
    MyaSemanticState,
    get_mya_renderer,
)


def test_mya_presentation_state_invariants() -> None:
    state = MyaPresentationState(
        expression="focused",
        pose="listening",
        activity="analyzing",
    )
    assert state.expression == "focused"
    assert state.pose == "listening"
    assert state.activity == "analyzing"


def test_renderers_conform_to_protocol() -> None:
    renderers = [
        DotMyaRenderer(),
        GlyphMyaRenderer(),
        AsciiMyaRenderer(),
        MinimalMyaRenderer(),
    ]
    for r in renderers:
        assert isinstance(r, MyaRenderer)


def test_dot_renderer_presence_and_speech() -> None:
    renderer = DotMyaRenderer()
    rs = MyaRenderState(
        status="PROCESSING",
        label="Analyzing dependencies",
        expression="focused",
    )

    presence = renderer.render_presence(rs, ascii_only=False)
    assert "Mya" in presence
    assert "●" in presence
    assert "[focused]" in presence

    speech = renderer.render_speech_bubble("Hello user!", rs)
    assert "Hello user!" in speech


def test_ascii_avatar_renderer_expressions() -> None:
    renderer = AsciiMyaRenderer()

    # Calm expression (default)
    rs_calm = MyaRenderState(expression="calm")
    avatar_calm = renderer.render_avatar(rs_calm, ascii_only=False)
    assert "◉ ◉" in avatar_calm
    assert "◡" in avatar_calm

    # Focused expression
    rs_focused = MyaRenderState(expression="focused")
    avatar_focused = renderer.render_avatar(rs_focused, ascii_only=False)
    assert "• •" in avatar_focused
    assert "─" in avatar_focused

    # Alert expression in ASCII mode
    rs_alert = MyaRenderState(expression="alert")
    avatar_alert_ascii = renderer.render_avatar(rs_alert, ascii_only=True)
    assert "! !" in avatar_alert_ascii
    assert "+-----+" in avatar_alert_ascii


def test_get_mya_renderer_factory() -> None:
    assert isinstance(get_mya_renderer("dot"), DotMyaRenderer)
    assert isinstance(get_mya_renderer("glyph"), GlyphMyaRenderer)
    assert isinstance(get_mya_renderer("ascii"), AsciiMyaRenderer)
    assert isinstance(get_mya_renderer("minimal"), MinimalMyaRenderer)
    # Default fallback is dot
    assert isinstance(get_mya_renderer("unknown"), DotMyaRenderer)


def test_semantic_states_enum() -> None:
    assert MyaSemanticState.IDLE == "IDLE"
    assert MyaSemanticState.APPROVAL_NEEDED == "APPROVAL_NEEDED"
    assert MyaSemanticState.SPEAKING == "SPEAKING"
