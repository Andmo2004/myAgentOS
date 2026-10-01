"""Paths resolution and constants for Mya Home and configuration files (§8, §10, §15)."""

from __future__ import annotations

import os
from pathlib import Path

ENV_MYA_HOME: str = "MYA_HOME"
DEFAULT_MYA_HOME: Path = Path.home() / ".agenticos"


def resolve_mya_home(explicit_home: Path | str | None = None) -> Path:
    """Resolves the active Mya Home directory.

    Precedence:
    1. Explicit path parameter (if provided)
    2. Environment variable MYA_HOME (if set and non-empty)
    3. Persisted mya.home in default ~/.agenticos/config/settings.yaml (if present)
    4. Default location: ~/.agenticos
    """
    if explicit_home is not None:
        p = Path(explicit_home).expanduser()
        return p.resolve() if p.is_absolute() else p

    env_val = os.environ.get(ENV_MYA_HOME)
    if env_val and env_val.strip():
        p = Path(env_val.strip()).expanduser()
        return p.resolve() if p.is_absolute() else p

    default_settings = DEFAULT_MYA_HOME / "config" / "settings.yaml"
    if default_settings.is_file():
        try:
            import yaml  # type: ignore[import-untyped]

            raw = default_settings.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
            if isinstance(data, dict):
                mya_section = data.get("mya")
                if isinstance(mya_section, dict):
                    configured_home = mya_section.get("home")
                    if configured_home and isinstance(configured_home, str):
                        p = Path(configured_home).expanduser()
                        return p.resolve() if p.is_absolute() else p
        except Exception:
            pass

    return DEFAULT_MYA_HOME.resolve()


def settings_path(mya_home: Path | str | None = None) -> Path:
    """Returns the settings.yaml path within Mya Home."""
    home = resolve_mya_home(mya_home)
    return home / "config" / "settings.yaml"


def version_path(mya_home: Path | str | None = None) -> Path:
    """Returns the version.json path within Mya Home."""
    home = resolve_mya_home(mya_home)
    return home / "version.json"


def project_registry_path(mya_home: Path | str | None = None) -> Path:
    """Returns the project registry directory or file within Mya Home."""
    home = resolve_mya_home(mya_home)
    return home / "projects" / "registry" / "projects.json"
