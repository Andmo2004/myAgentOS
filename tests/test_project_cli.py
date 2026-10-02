from pathlib import Path

import pytest

from myagentos.cli import cmd_project
from myagentos.core.store.event_store import EventStore
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService


@pytest.fixture
def project_service(tmp_path: Path):
    reg_file = tmp_path / "projects.json"
    event_dir = tmp_path / "events"
    reg = ProjectRegistry(reg_file)
    store = EventStore(root_dir=event_dir)
    return ProjectManagerService(registry=reg, event_store=store)


def test_cli_project_list_empty(capsys, project_service, monkeypatch):
    monkeypatch.setattr("myagentos.cli.ProjectManagerService", lambda: project_service)
    cmd_project(action="list")
    captured = capsys.readouterr().out
    assert "Active Projects (0)" in captured


def test_cli_project_add_and_list(capsys, project_service, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("myagentos.cli.ProjectManagerService", lambda: project_service)
    repo = tmp_path / "my-cool-app"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'my-cool-app'\n")

    cmd_project(action="add", target=str(repo), name="CoolApp")
    captured = capsys.readouterr().out
    assert "Project added" in captured
    assert "CoolApp" in captured

    cmd_project(action="list")
    list_out = capsys.readouterr().out
    assert "CoolApp" in list_out
    assert "ACTIVE" in list_out


def test_cli_project_new(capsys, project_service, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("myagentos.cli.ProjectManagerService", lambda: project_service)
    cmd_project(action="new", target="BrandNew", repo_path=str(tmp_path))
    captured = capsys.readouterr().out
    assert "Project created: BrandNew" in captured
    assert (tmp_path / "BrandNew").exists()


def test_cli_project_trash_flow(capsys, project_service, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("myagentos.cli.ProjectManagerService", lambda: project_service)
    repo = tmp_path / "disposable"
    repo.mkdir()
    p = project_service.add_project(repo, name="Disposable")

    # Move to trash
    cmd_project(action="trash", target="move", secondary="Disposable")
    out = capsys.readouterr().out
    assert "Moved 'Disposable' to Trash" in out
    assert repo.exists()  # Safety invariant: files remain untouched

    # Trash list
    cmd_project(action="trash", target="list")
    list_out = capsys.readouterr().out
    assert "Disposable" in list_out
    assert "Project Trash (1)" in list_out

    # Restore
    cmd_project(action="trash", target="restore", secondary="Disposable")
    restore_out = capsys.readouterr().out
    assert "Restored 'Disposable' to ACTIVE" in restore_out

    # Move again and purge without confirm (should exit 1)
    project_service.move_to_trash(p.project_id)
    with pytest.raises(SystemExit) as exc:
        cmd_project(action="trash", target="purge", secondary="Disposable", confirm=False)
    assert exc.value.code == 1

    # Purge with confirm
    cmd_project(action="trash", target="purge", secondary="Disposable", confirm=True)
    purge_out = capsys.readouterr().out
    assert "Permanently deleted registration for 'Disposable'" in purge_out
    assert repo.exists()  # Invariant: directory still on disk!


def test_cli_project_json_and_filter(capsys, project_service, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("myagentos.cli.ProjectManagerService", lambda: project_service)
    p1_dir = tmp_path / "app-frontend"
    p1_dir.mkdir()
    project_service.add_project(p1_dir, name="Frontend")

    cmd_project(action="list", json_output=True)
    out = capsys.readouterr().out
    assert '"name": "Frontend"' in out

    cmd_project(action="list", search="NonExistent")
    search_out = capsys.readouterr().out
    assert "Active Projects (0)" in search_out


def test_cli_project_init_and_reset(capsys, project_service, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("myagentos.cli.ProjectManagerService", lambda: project_service)
    target = tmp_path / "cli-init-repo"
    target.mkdir()

    # 1. CLI init action
    cmd_project(action="init", target=str(target), name="CLI Init")
    init_out = capsys.readouterr().out
    assert "Estructura de Mya verificada" in init_out
    assert (target / "MYA.md").is_file()
    assert (target / ".mya" / "skills").is_dir()

    # Edit MYA.md
    (target / "MYA.md").write_text("# Custom\n- CLI test edit\n", encoding="utf-8")

    # 2. CLI reset action
    cmd_project(action="reset", target=str(target), name="CLI Init")
    reset_out = capsys.readouterr().out
    assert "Estructura de Mya reinicializada" in reset_out
    assert "Backup de MYA.md" in reset_out
    assert (target / "MYA.md.bak").is_file()
    assert "CLI test edit" in (target / "MYA.md.bak").read_text(encoding="utf-8")
    assert "## Rules" in (target / "MYA.md").read_text(encoding="utf-8")
