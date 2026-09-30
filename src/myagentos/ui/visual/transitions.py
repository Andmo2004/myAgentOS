"""State transitions and duration budgeting for micro-animations (§8.3).

Ensures bounded, non-blocking visual progressions.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict

from myagentos.ui.theme.symbols import VisualStatus


class TransitionSpec(BaseModel):
    """Specification of an operational state transition."""

    model_config = ConfigDict(frozen=True)

    from_status: VisualStatus
    to_status: VisualStatus
    duration_ms: int = 250
    semantic: bool = True


DEFAULT_DURATION_MS: Final[int] = 250
MIN_DURATION_MS: Final[int] = 120
MAX_DURATION_MS: Final[int] = 500


def get_transition_spec(
    from_status: VisualStatus,
    to_status: VisualStatus,
    duration_ms: int = DEFAULT_DURATION_MS,
) -> TransitionSpec:
    """Creates a clamped, bounded transition spec (§8.3)."""
    bounded = max(MIN_DURATION_MS, min(MAX_DURATION_MS, duration_ms))
    return TransitionSpec(
        from_status=from_status,
        to_status=to_status,
        duration_ms=bounded,
        semantic=True,
    )
