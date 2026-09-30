"""Persistent registry storage for registered projects.

Follows §19 of docs/agentic-os-feature-project-manager-explorer.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from myagentos.projects.models import Project

logger = logging.getLogger(__name__)


def _default_registry_path() -> Path:
    return Path.home() / ".myagentos" / "projects.json"


class ProjectRegistry:
    """Manages persistent JSON catalog of projects registered in Agentic OS."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self.storage_path = Path(storage_path) if storage_path else _default_registry_path()

    def _read_data(self) -> dict[str, dict[str, Any]]:
        if not self.storage_path.is_file():
            return {}
        try:
            raw = self.storage_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.debug("Failed reading registry file %s: %s", self.storage_path, exc)
            return {}

    def _write_data(self, data: dict[str, dict[str, Any]]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def save_project(self, project: Project) -> None:
        """Inserts or updates a project in the persistent registry."""
        data = self._read_data()
        data[project.project_id] = project.model_dump(mode="json")
        self._write_data(data)

    def get_project(self, project_id: str) -> Project | None:
        """Retrieves a project by its stable identifier."""
        data = self._read_data()
        raw = data.get(project_id)
        if not raw:
            return None
        try:
            return Project.model_validate(raw)
        except Exception as exc:
            logger.debug("Failed validating project %s: %s", project_id, exc)
            return None

    def get_by_path(self, path: Path | str) -> Project | None:
        """Finds a registered project by its canonical path."""
        target = str(Path(path).resolve())
        for proj in self.list_projects():
            if str(Path(proj.path).resolve()) == target:
                return proj
        return None

    def get_by_name(self, name: str) -> Project | None:
        """Finds a project by exact or case-insensitive name match."""
        target = name.strip().lower()
        for proj in self.list_projects():
            if proj.name.strip().lower() == target:
                return proj
        return None

    def list_projects(self) -> list[Project]:
        """Returns all registered projects from storage."""
        data = self._read_data()
        projects: list[Project] = []
        for raw in data.values():
            try:
                projects.append(Project.model_validate(raw))
            except Exception as exc:
                logger.debug("Skipping invalid project entry: %s", exc)
        return projects

    def remove_project(self, project_id: str) -> bool:
        """Permanently deletes the project registration entry from storage."""
        data = self._read_data()
        if project_id in data:
            del data[project_id]
            self._write_data(data)
            return True
        return False
