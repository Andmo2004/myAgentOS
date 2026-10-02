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
    assert (proj_dir / ".myagentos" / "memory").is_dir()
    assert (proj_dir / "MYA.md").is_file()
    assert (proj_dir / ".mya" / "skills").is_dir()
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
    assert (existing_dir / ".myagentos" / "memory").is_dir()
    assert (existing_dir / "MYA.md").is_file()
    assert (existing_dir / ".mya" / "skills").is_dir()

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


def test_project_mya_environment_creation_and_non_overwriting(tmp_path: Path) -> None:
    """Verify project creation creates Mya files without overwriting existing files."""
    reg = ProjectRegistry(storage_path=tmp_path / "reg.json")
    service = ProjectManagerService(registry=reg)

    # 1. Project without any pre-existing Mya files
    clean_dir = tmp_path / "clean-repo"
    clean_dir.mkdir()
    (clean_dir / "app.py").write_text("print('test')")

    service.add_project(path=clean_dir, name="Clean Repo")

    # Verify files created inside project folder (NOT in global mya home)
    mya_md = clean_dir / "MYA.md"
    assert mya_md.is_file()
    content = mya_md.read_text(encoding="utf-8")
    assert "# MYA.md" in content
    assert "Clean Repo" in content
    assert "## Preferred Skills" in content
    assert "- #python" in content
    assert "- #testing" in content

    skills_dir = clean_dir / ".mya" / "skills"
    assert skills_dir.is_dir()
    assert (skills_dir / "README.md").is_file()

    memory_dir = clean_dir / ".myagentos" / "memory"
    assert memory_dir.is_dir()

    # 2. Project with PRE-EXISTING custom MYA.md (must NOT be overwritten)
    custom_dir = tmp_path / "custom-repo"
    custom_dir.mkdir()
    existing_mya = custom_dir / "MYA.md"
    existing_content = "# Custom Team Rules\n- Strictly zero-commit to main.\n"
    existing_mya.write_text(existing_content, encoding="utf-8")

    service.add_project(path=custom_dir, name="Custom Repo")

    # Verify pre-existing MYA.md content is preserved
    assert (custom_dir / "MYA.md").is_file()
    assert (custom_dir / "MYA.md").read_text(encoding="utf-8") == existing_content
    # Other missing directories were still created
    assert (custom_dir / ".mya" / "skills").is_dir()
    assert (custom_dir / ".myagentos" / "memory").is_dir()


def test_reset_project_mya_environment_creates_backup(tmp_path: Path):
    """Resetting project Mya environment creates backup of MYA.md and recreates fresh files."""
    repo_dir = tmp_path / "reset-repo"
    repo_dir.mkdir()

    # Step 1: Initial ensure
    res = ProjectManagerService.ensure_project_mya_environment(
        project_root=repo_dir,
        project_name="Reset Repo",
    )
    assert res["status"] == "ok"
    assert "MYA.md" in res["created"]
    assert (repo_dir / "MYA.md").is_file()
    assert (repo_dir / ".mya" / "skills").is_dir()
    assert (repo_dir / ".myagentos" / "memory").is_dir()

    # Step 2: Modify MYA.md with user edits
    mya_file = repo_dir / "MYA.md"
    mya_file.write_text("# Custom User Rules\n- User rule 1\n", encoding="utf-8")

    # Step 3: Run reset
    reset_res = ProjectManagerService.reset_project_mya_environment(
        project_root=repo_dir,
        project_name="Reset Repo",
    )
    assert reset_res["status"] == "ok"
    assert reset_res.get("reset") is True
    assert reset_res.get("backup") == "MYA.md.bak"

    # Backup file exists and has previous user edits
    backup_file = repo_dir / "MYA.md.bak"
    assert backup_file.is_file()
    assert "User rule 1" in backup_file.read_text(encoding="utf-8")

    # New MYA.md was regenerated with clean default structure
    new_mya = repo_dir / "MYA.md"
    assert new_mya.is_file()
    assert "Reset Repo" in new_mya.read_text(encoding="utf-8")
    assert "## Rules" in new_mya.read_text(encoding="utf-8")


def test_ensure_gitignore_creates_file_and_appends_entries(tmp_path: Path):
    """Ensure .gitignore creates missing file and appends Mya entries."""
    repo = tmp_path / "repo-gitignore"
    repo.mkdir()

    # 1. No .gitignore initially
    res = ProjectManagerService.ensure_gitignore_entries(repo)
    assert res["status"] == "ok"
    assert len(res["added"]) == 4
    assert (repo / ".gitignore").is_file()
    content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".myagentos/" in content
    assert ".mya/" in content
    assert "MYA.md" in content
    assert "MYA.md.bak" in content

    # 2. Re-running should detect everything as already present
    res2 = ProjectManagerService.ensure_gitignore_entries(repo)
    assert res2["status"] == "ok"
    assert len(res2["added"]) == 0
    assert len(res2["already_present"]) == 4


def test_ensure_gitignore_appends_only_missing_and_respects_globs(tmp_path: Path):
    """Ensure .gitignore appends only missing entries without duplicating items."""
    repo = tmp_path / "repo-partial-gitignore"
    repo.mkdir()
    (repo / ".gitignore").write_text("build/\n.myagentos/\nmya*.md\n", encoding="utf-8")

    res = ProjectManagerService.ensure_gitignore_entries(repo)
    assert res["status"] == "ok"
    # .myagentos/ is exact match; MYA.md matches mya*.md glob
    # Only .mya/ and MYA.md.bak should be missing
    assert ".mya/" in res["added"]
    assert "MYA.md.bak" in res["added"]
    assert "MYA.md" not in res["added"]
    assert ".myagentos/" not in res["added"]

    content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "build/" in content
    assert ".mya/" in content
    assert "MYA.md.bak" in content
