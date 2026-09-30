"""Unit tests for Project Registry persistent storage."""

from pathlib import Path

from myagentos.projects.models import Project, ProjectState
from myagentos.projects.registry import ProjectRegistry


def test_registry_save_and_lookup(tmp_path: Path) -> None:
    """Verify storing, retrieving by id, name, and path."""
    reg_file = tmp_path / "projects.json"
    registry = ProjectRegistry(storage_path=reg_file)

    p1 = Project(
        project_id="proj-1",
        name="Agentic OS",
        path=str(tmp_path / "agentic"),
        state=ProjectState.ACTIVE,
    )
    p2 = Project(
        project_id="proj-2",
        name="Acme Shop",
        path=str(tmp_path / "acme"),
        state=ProjectState.TRASHED,
    )

    registry.save_project(p1)
    registry.save_project(p2)

    # Lookup by ID
    loaded = registry.get_project("proj-1")
    assert loaded is not None
    assert loaded.name == "Agentic OS"
    assert loaded.state == ProjectState.ACTIVE

    # Lookup by Name
    by_name = registry.get_by_name("acme shop")
    assert by_name is not None
    assert by_name.project_id == "proj-2"

    # Lookup by Path
    by_path = registry.get_by_path(tmp_path / "agentic")
    assert by_path is not None
    assert by_path.project_id == "proj-1"

    # List all
    all_projs = registry.list_projects()
    assert len(all_projs) == 2

    # Remove
    removed = registry.remove_project("proj-1")
    assert removed is True
    assert registry.get_project("proj-1") is None
    assert len(registry.list_projects()) == 1
