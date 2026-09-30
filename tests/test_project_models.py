"""Unit tests for Project Manager models."""

import pytest
from pydantic import ValidationError

from myagentos.projects.models import (
    Project,
    ProjectCreationSpec,
    ProjectFilter,
    ProjectState,
)


def test_project_model_immutability() -> None:
    """Verify that Project models are frozen and immutable."""
    project = Project(
        project_id="p-1",
        name="Test Project",
        path="/tmp/test",
    )
    with pytest.raises(ValidationError):
        setattr(project, "name", "Modified Name")


def test_project_state_enum() -> None:
    """Verify all defined project states exist."""
    assert ProjectState.ACTIVE == "active"
    assert ProjectState.SCANNING == "scanning"
    assert ProjectState.READY == "ready"
    assert ProjectState.STALE == "stale"
    assert ProjectState.DISCONNECTED == "disconnected"
    assert ProjectState.TRASHED == "trashed"
    assert ProjectState.DELETED == "deleted"


def test_project_filter_model() -> None:
    """Verify filtering model defaults."""
    f = ProjectFilter(tag="Python", state=ProjectState.ACTIVE)
    assert f.tag == "Python"
    assert f.state == ProjectState.ACTIVE
    assert f.query is None


def test_project_creation_spec() -> None:
    """Verify creation specification model."""
    spec = ProjectCreationSpec(name="App", path="/path/to/app")
    assert spec.initialize_git is True
    assert spec.template is None
