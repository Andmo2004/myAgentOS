"""Motion control and reduced motion mode management (§21).

Supports three modes:
- full: Micro-animations enabled (spinners, pulses, transitions).
- reduced: Only essential state transitions. No continuous spinners/pulses.
- off: All animations disabled. Instant static representations.
"""

from enum import StrEnum
from typing import Final


class MotionMode(StrEnum):
    """User-configurable motion preferences (§21)."""

    FULL = "full"
    REDUCED = "reduced"
    OFF = "off"


class MotionController:
    """Controls whether animations and transitions should advance."""

    _instance: "MotionController | None" = None

    def __init__(self, mode: MotionMode = MotionMode.FULL) -> None:
        self._mode: MotionMode = mode

    @classmethod
    def get_instance(cls) -> "MotionController":
        if cls._instance is None:
            cls._instance = MotionController()
        return cls._instance

    @property
    def mode(self) -> MotionMode:
        return self._mode

    def set_mode(self, mode: MotionMode | str) -> MotionMode:
        if isinstance(mode, str):
            clean = mode.strip().lower()
            try:
                self._mode = MotionMode(clean)
            except ValueError:
                valid = ", ".join(m.value for m in MotionMode)
                raise ValueError(f"Invalid motion mode '{mode}'. Choose from: {valid}")
        else:
            self._mode = mode
        return self._mode

    @property
    def allows_continuous_animation(self) -> bool:
        """True if continuous spinners/pulses are permitted."""
        return self._mode == MotionMode.FULL

    @property
    def allows_transitions(self) -> bool:
        """True if short state change transitions are permitted."""
        return self._mode in (MotionMode.FULL, MotionMode.REDUCED)


DEFAULT_MOTION_CONTROLLER: Final[MotionController] = MotionController.get_instance()
