"""UI Event Adapter: projects Event Store events to human-readable UI events.

The UI is a derived view of the Event Store (§16).
No second FSM exists in the UI. All state comes from events.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from myagentos.core.models.event import Event
from myagentos.mya.explanations import translate_event, translate_state


class UIEvent(BaseModel):
    """A projected event for the UI layer."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    job_id: str
    timestamp: datetime
    state: str
    state_label: str
    human_message: str
    severity: str = "info"
    progress: float | None = None


def project_event(event: Event) -> UIEvent:
    """Project a raw Event Store event into a UI-friendly representation."""
    state_label = translate_state(event.state)
    human_msg = translate_event(event.event_name.value)

    # Determine severity from event type
    severity = "info"
    if "FAIL" in event.event_name.value or "VIOLATION" in event.event_name.value:
        severity = "error"
    elif "WAIT" in event.state or "ESCALATED" in event.state:
        severity = "warning"

    return UIEvent(
        event_id=event.event_id,
        job_id=event.job_id,
        timestamp=event.timestamp,
        state=event.state,
        state_label=state_label,
        human_message=human_msg,
        severity=severity,
    )
