"""Mya Home filesystem initializer (§10, §17).

Creates the standardized directory structure and metadata files for Mya Home.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SUBDIRECTORIES: tuple[str, ...] = (
    "config",
    "config/profiles",
    "sessions",
    "projects/registry",
    "memory/user",
    "memory/mya",
    "memory/projects",
    "telemetry",
    "cache",
    "runtime/locks",
    "runtime/sockets",
    "runtime/state",
    "logs",
)


def initialize_mya_home(path: Path | str) -> Path:
    """Initializes the Mya Home directory structure.

    Creates required subdirectories and writes version.json if not present.
    """
    home = Path(path).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)

    for subdir in SUBDIRECTORIES:
        (home / subdir).mkdir(parents=True, exist_ok=True)

    version_file = home / "version.json"
    if not version_file.exists():
        version_payload = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "agentic_os_version": "2.2",
            "format": "mya_home_v1",
        }
        version_file.write_text(
            json.dumps(version_payload, indent=2),
            encoding="utf-8",
        )
        logger.info("Created Mya Home version.json at %s", version_file)

    logger.info("Initialized Mya Home directory structure at %s", home)
    return home
