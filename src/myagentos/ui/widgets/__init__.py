"""UI Widgets package (§33)."""

from myagentos.ui.widgets.agent_tree import AgentTreeWidget
from myagentos.ui.widgets.chat import (
    ChatMessage,
    CommandSuggestions,
    PromptInput,
    ThinkingIndicator,
    WelcomePanel,
)
from myagentos.ui.widgets.file_activity import FileActivityWidget
from myagentos.ui.widgets.job_monitor import JobMonitorWidget
from myagentos.ui.widgets.mya_avatar import MyaAvatarWidget
from myagentos.ui.widgets.mya_panel import MyaPanelWidget
from myagentos.ui.widgets.token_meter import TokenMeterWidget
from myagentos.ui.widgets.verification_panel import VerificationPanelWidget

__all__ = [
    "AgentTreeWidget",
    "ChatMessage",
    "CommandSuggestions",
    "FileActivityWidget",
    "JobMonitorWidget",
    "MyaAvatarWidget",
    "MyaPanelWidget",
    "PromptInput",
    "ThinkingIndicator",
    "TokenMeterWidget",
    "VerificationPanelWidget",
    "WelcomePanel",
]
