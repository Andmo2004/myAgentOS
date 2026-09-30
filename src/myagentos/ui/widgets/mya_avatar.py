"""Textual widget for rendering Mya's visual character avatar (§14, §15)."""

from typing import Any

from textual.widgets import Static

from myagentos.mya.presentation import MyaRenderState, get_mya_renderer
from myagentos.ui.theme.themes import ThemeRegistry


class MyaAvatarWidget(Static):
    """Visual avatar representation of Mya (dot, glyph, ascii, minimal)."""

    def __init__(
        self,
        avatar_mode: str = "dot",
        expression: str = "calm",
        status: str = "IDLE",
        label: str = "Ready",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.state = MyaRenderState(
            status=status,
            label=label,
            expression=expression,
            avatar_mode=avatar_mode,
        )
        super().__init__(*args, **kwargs)

    def set_avatar_mode(self, mode: str) -> None:
        self.state = self.state.model_copy(update={"avatar_mode": mode})
        self.refresh()

    def set_expression(self, expression: str) -> None:
        self.state = self.state.model_copy(update={"expression": expression})
        self.refresh()

    def set_status(self, status: str, label: str = "") -> None:
        updates: dict[str, Any] = {"status": status}
        if label:
            updates["label"] = label
        self.state = self.state.model_copy(update=updates)
        self.refresh()

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        renderer = get_mya_renderer(self.state.avatar_mode)
        return renderer.render_avatar(self.state, ascii_only=theme.ascii_only)
