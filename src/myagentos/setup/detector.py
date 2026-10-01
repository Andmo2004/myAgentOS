"""First-run detection logic (§4).

Determines whether Mya requires initial first-run onboarding.
"""

from __future__ import annotations

from pathlib import Path


def is_setup_complete(mya_home: Path | str | None = None) -> bool:
    """Checks whether the first-run setup has been completed.

    Returns True only if settings.yaml exists and contains setup.completed = true.
    """
    from myagentos.config.loader import load_config
    from myagentos.config.paths import resolve_mya_home

    home = resolve_mya_home(mya_home)
    config = load_config(mya_home=home)
    if config is None:
        return False
    return bool(config.setup.completed)


def needs_first_run(mya_home: Path | str | None = None) -> bool:
    """Returns True if Mya must launch the first-run onboarding wizard."""
    return not is_setup_complete(mya_home=mya_home)
