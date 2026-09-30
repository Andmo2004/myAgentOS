"""Mya panel widget displaying presence header and conversational bubble (§6.2, §14)."""

from typing import Any

from textual.widgets import Static

from myagentos.mya.presentation import MyaRenderState, get_mya_renderer
from myagentos.ui.theme.themes import ThemeRegistry


class MyaPanelWidget(Static):
    """Presence bar and speech bubble for Mya."""

    def __init__(
        self,
        message: str = "",
        status: str = "IDLE",
        label: str = "Ready",
        expression: str = "calm",
        avatar_mode: str = "dot",
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.message = message
        self.state = MyaRenderState(
            status=status,
            label=label,
            expression=expression,
            avatar_mode=avatar_mode,
        )
        super().__init__(*args, **kwargs)

    def update_message(
        self,
        message: str,
        status: str = "SPEAKING",
        expression: str = "calm",
    ) -> None:
        self.message = message
        self.state = self.state.model_copy(
            update={"status": status, "expression": expression}
        )
        self.refresh()

    def render(self) -> str:
        theme = ThemeRegistry.get_instance().active_theme
        renderer = get_mya_renderer(self.state.avatar_mode)
        if not self.message:
            return renderer.render_presence(self.state, ascii_only=theme.ascii_only)
        return renderer.render_speech_bubble(
            self.message, self.state, ascii_only=theme.ascii_only
        )
