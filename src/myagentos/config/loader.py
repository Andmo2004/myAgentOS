"""Configuration loader and saver for settings.yaml (§15)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from myagentos.config.paths import settings_path
from myagentos.setup.models import SetupConfig

logger = logging.getLogger(__name__)


def load_config(
    path: Path | str | None = None,
    mya_home: Path | str | None = None,
) -> SetupConfig | None:
    """Loads SetupConfig from settings.yaml.

    Returns None if the file does not exist or fails to parse.
    """
    target = Path(path) if path else settings_path(mya_home)
    if not target.is_file():
        return None

    try:
        raw_text = target.read_text(encoding="utf-8")
        if not raw_text.strip():
            return None
        raw_data = yaml.safe_load(raw_text)
        if not isinstance(raw_data, dict):
            return None
        return SetupConfig.model_validate(raw_data)
    except Exception as exc:
        logger.warning("Failed to load settings from %s: %s", target, exc)
        return None


def save_config(
    config: SetupConfig,
    mya_home: Path | str | None = None,
    path: Path | str | None = None,
) -> Path:
    """Saves SetupConfig to settings.yaml.

    Ensures the parent directory exists.
    """
    target = Path(path) if path else settings_path(mya_home)
    target.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = config.model_dump(mode="json")
    yaml_content = yaml.safe_dump(
        data,
        sort_keys=False,
        indent=2,
        allow_unicode=True,
    )
    target.write_text(yaml_content, encoding="utf-8")
    return target
