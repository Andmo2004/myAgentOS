"""Unit tests for ProjectManagerService lifecycle, soft delete, and auditing."""

from pathlib import Path

import pytest

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.projects.models import (
    ProjectFilter,
    ProjectState,
)
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService


def test_create_and_add_project(tmp_path: Path) -> None:
    """Verify creating a new project and adding an existing repository."""
    reg = ProjectRegistry(storage_path=tmp_path / "reg.json")
    event_store = EventStore(root_dir=tmp_path / "events")
    service = ProjectManagerService(registry=reg, event_store=event_store)

    # 1. Create project
    proj_dir = tmp_path / "my-new-app"
    p1 = service.create_project(name="My New App", path=proj_dir)

    assert p1.name == "My New App"
    assert p1.state == ProjectState.ACTIVE
    assert proj_dir.is_dir()
    assert (proj_dir / ".git").is_dir()
    assert p1.mya_namespace_id == f"/vault/Proyectos/{p1.project_id}"

    # Verify event
    events = event_store.load_events(job_id=p1.project_id)
    created_events = [e for e in events if e.event_name == EventName.PROJECT_CREATED]
    assert len(created_events) == 1
    assert created_events[0].actor == EventActor.PROJECT_MANAGER

    # 2. Add existing repository
    existing_dir = tmp_path / "existing-service"
    existing_dir.mkdir()
    (existing_dir / "pyproject.toml").write_text("[project]\nname='service'\n")
    p2 = service.add_project(path=existing_dir)

    assert p2.name == "existing-service"
    assert p2.state == ProjectState.ACTIVE

    # 3. Duplicate protection
    with pytest.raises(ValueError, match="already registered"):
        service.add_project(path=existing_dir)


def test_filter_and_search_projects(tmp_path: Path) -> None:
    """Verify filtering by query, tag, and status."""
    reg = ProjectRegistry(storage_path=tmp_path / "reg.json")
    service = ProjectManagerService(registry=reg)

    d1 = tmp_path / "app-one"
    d1.mkdir()
    (d1 / "main.py").write_text("print('hello')")
    service.add_project(path=d1, name="App One")

    d2 = tmp_path / "shop-api"
    d2.mkdir()
    (d2 / "app.py").write_text("import fastapi")
    (d2 / "pyproject.toml").write_text("[project]\nname='shop'\ndependencies=['fastapi']")
    service.add_project(path=d2, name="Shop API")

    # Search by name query
    results_q = service.list_projects(ProjectFilter(query="shop"))
    assert len(results_q) == 1
    assert results_q[0].name == "Shop API"

    # Search by tag
    results_tag = service.list_projects(ProjectFilter(tag="Python"))
    assert len(results_tag) >= 1


def test_soft_delete_restore_and_purge_lifecycle(tmp_path: Path) -> None:
    """Verify two-stage delete: soft delete to Trash, restore, and permanent delete."""
    reg = ProjectRegistry(storage_path=tmp_path / "reg.json")
    event_store = EventStore(root_dir=tmp_path / "events")
    service = ProjectManagerService(registry=reg, event_store=event_store)

    proj_dir = tmp_path / "target-project"
    proj_dir.mkdir()
    (proj_dir / "code.py").write_text("# critical code")
    project = service.add_project(path=proj_dir, name="Target Project")
    p_id = project.project_id

    # 1. Soft delete -> Move to Trash
    trashed = service.move_to_trash(p_id)
    assert trashed.state == ProjectState.TRASHED
    assert trashed.trashed_at is not None

    # CRITICAL: Repository code must NOT be touched
    assert (proj_dir / "code.py").is_file()
    assert (proj_dir / "code.py").read_text() == "# critical code"

    # Must be hidden from active list
    active_projects = service.list_projects()
    assert all(p.project_id != p_id for p in active_projects)

    # Must appear in Trash
    trash_projects = service.list_trash()
    assert any(p.project_id == p_id for p in trash_projects)

    # Check EventStore
    events_trash = event_store.load_events(job_id=p_id)
    assert any(e.event_name == EventName.PROJECT_MOVED_TO_TRASH for e in events_trash)

    # 2. Restore from Trash
    restored = service.restore_project(p_id)
    assert restored.state == ProjectState.ACTIVE
    assert restored.trashed_at is None
    assert any(p.project_id == p_id for p in service.list_projects())

    # Check EventStore
    events_restore = event_store.load_events(job_id=p_id)
    assert any(e.event_name == EventName.PROJECT_RESTORED for e in events_restore)

    # 3. Permanent delete requires explicit confirmation
    service.move_to_trash(p_id)
    with pytest.raises(ValueError, match="Explicit confirmation is required"):
        service.delete_permanently(p_id, confirm=False)

    # With confirmation
    purged = service.delete_permanently(p_id, confirm=True)
    assert purged is True
    assert service.get_project(p_id) is None

    # CRITICAL: Physical repository is STILL intact on disk!
    assert (proj_dir / "code.py").is_file()

    # Check EventStore has final audit event
    events_purge = event_store.load_events(job_id=p_id)
    assert any(e.event_name == EventName.PROJECT_PERMANENTLY_DELETED for e in events_purge)
