"""Project Manager & Project Explorer package for Agentic OS.

Follows docs/agentic-os-feature-project-manager-explorer.md.
"""

from myagentos.projects.models import (
    Project,
    ProjectCreationSpec,
    ProjectFilter,
    ProjectState,
)
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService

__all__ = [
    "Project",
    "ProjectCreationSpec",
    "ProjectFilter",
    "ProjectManagerService",
    "ProjectRegistry",
    "ProjectState",
]
