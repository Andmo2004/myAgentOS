from pathlib import Path

from myagentos.mya.context import ConversationContextService
from myagentos.projects.models import Project, ProjectState
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session


def _project(project_id: str, name: str, path: Path, state: ProjectState) -> Project:
    return Project(
        project_id=project_id,
        name=name,
        path=str(path),
        state=state,
        branch="main",
        commit_short="a1b2c3d",
    )


def test_context_uses_visible_registry_projects_and_omits_paths_by_default(tmp_path: Path) -> None:
    active_path = tmp_path / "private-project-path"
    active_path.mkdir()
    registry = ProjectRegistry(tmp_path / "registry.json")
    registry.save_project(_project("one", "alpha", active_path, ProjectState.ACTIVE))
    registry.save_project(
        _project("trash", "hidden-trash", tmp_path / "trashed", ProjectState.TRASHED)
    )
    registry.save_project(
        _project("deleted", "hidden-deleted", tmp_path / "deleted", ProjectState.DELETED)
    )
    session = Session(
        project_id="one",
        repository="alpha",
        branch="main",
        commit_short="a1b2c3d",
        working_tree_clean=False,
        repo_root=active_path,
    )

    context = ConversationContextService(ProjectManagerService(registry=registry)).build_context(
        session
    )
    prompt = context.to_prompt()

    assert context.projects_available is True
    assert context.project_count == 1
    assert [project.name for project in context.projects] == ["alpha"]
    assert context.active_project is not None
    assert context.active_project.name == "alpha"
    assert "status: dirty" in prompt
    assert "path:" not in prompt
    assert "private-project-path" not in prompt
    assert "hidden-trash" not in prompt
    assert "hidden-deleted" not in prompt


def test_context_includes_path_only_when_requested(tmp_path: Path) -> None:
    project_path = tmp_path / "alpha"
    project_path.mkdir()
    registry = ProjectRegistry(tmp_path / "registry.json")
    registry.save_project(_project("one", "alpha", project_path, ProjectState.ACTIVE))
    service = ConversationContextService(ProjectManagerService(registry=registry))

    context = service.build_context(None, "¿Cuál es la ruta del proyecto alpha?")

    assert context.projects[0].path == str(project_path)
    assert f"path: {project_path}" in context.to_prompt()


def test_context_marks_project_registry_unavailable() -> None:
    class UnavailableProjectService:
        def list_projects(self) -> list[Project]:
            raise OSError("registry unavailable")

    context = ConversationContextService(UnavailableProjectService()).build_context(None)  # type: ignore[arg-type]

    assert context.projects_available is False
    assert "Project registry: unavailable" in context.to_prompt()
