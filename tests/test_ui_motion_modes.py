"""Tests for motion modes and animation gating (§21)."""

import pytest

from myagentos.ui.visual.motion import MotionController, MotionMode


def test_motion_controller_modes() -> None:
    ctrl = MotionController(mode=MotionMode.FULL)
    assert ctrl.allows_continuous_animation is True
    assert ctrl.allows_transitions is True

    ctrl.set_mode(MotionMode.REDUCED)
    assert ctrl.allows_continuous_animation is False
    assert ctrl.allows_transitions is True

    ctrl.set_mode(MotionMode.OFF)
    assert ctrl.allows_continuous_animation is False
    assert ctrl.allows_transitions is False

    # String input
    ctrl.set_mode("full")
    assert ctrl.mode == MotionMode.FULL

    with pytest.raises(ValueError):
        ctrl.set_mode("invalid_mode")
