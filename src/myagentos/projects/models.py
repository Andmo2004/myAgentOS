"""Data models for Project Manager & Project Explorer.

Follows §3, §4, §19 of docs/agentic-os-feature-project-manager-explorer.md.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from myagentos.categorization.models import ProjectProfile, VisibleTag


class ProjectState(StrEnum):
    """Lifecycle states of a project in the Project Manager (§4)."""

    ACTIVE = "active"
    SCANNING = "scanning"
    READY = "ready"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    TRASHED = "trashed"
    DELETED = "deleted"


class Project(BaseModel):
    """Persistent representation of a registered project in Agentic OS (§3, §19).

    Separates Agentic OS registration from physical repository existence.
    """

    model_config = ConfigDict(frozen=True)

    project_id: str
    name: str
    description: str = ""
    path: str

    state: ProjectState = ProjectState.ACTIVE

    remotes: dict[str, str] = Field(default_factory=dict)
    branch: str | None = None
    commit: str | None = None
    commit_short: str | None = None

    mya_enabled: bool = True
    mya_namespace_id: str = ""

    profile: ProjectProfile | None = None
    visible_tags: list[VisibleTag] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trashed_at: datetime | None = None
    deleted_at: datetime | None = None


class ProjectFilter(BaseModel):
    """Query criteria for filtering projects in Explorer (§22)."""

    model_config = ConfigDict(frozen=True)

    query: str | None = None
    tag: str | None = None
    state: ProjectState | None = None
    language: str | None = None


class ProjectCreationSpec(BaseModel):
    """Specification for creating a brand new project (§6)."""

    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    template: str | None = None
    initialize_git: bool = True
