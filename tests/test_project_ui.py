from pathlib import Path

import pytest

from myagentos.core.store.event_store import EventStore
from myagentos.gateway.client import ModelGateway
from myagentos.gateway.mock_adapter import MockProviderAdapter
from myagentos.mya.agent import MyaAgent
from myagentos.projects.models import Project, ProjectState
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.commands import SlashCommandKind, parse_input
from myagentos.ui.screens.projects import ConfirmPermanentDeleteModal, ProjectsScreen
from myagentos.ui.session import create_session


@pytest.fixture
def project_service(tmp_path: Path):
    reg_file = tmp_path / "projects.json"
    event_dir = tmp_path / "events"
    reg = ProjectRegistry(reg_file)
    store = EventStore(root_dir=event_dir)
    return ProjectManagerService(registry=reg, event_store=store)


@pytest.fixture
def mya_agent():
    gw = ModelGateway()
    gw.register_adapter("mock", MockProviderAdapter())
    return MyaAgent(gateway=gw, model_id="mock")


def test_slash_command_projects():
    cmd = parse_input("/projects")
    assert cmd.kind == SlashCommandKind.PROJECTS


def test_mya_converse_project_queries(mya_agent, project_service, tmp_path: Path, monkeypatch):
    monkeypatch.setattr("myagentos.projects.service.ProjectManagerService", lambda: project_service)

    # 1. Empty projects list
    resp1 = mya_agent.converse("muéstrame mis proyectos")
    assert "No tienes ningún proyecto registrado" in resp1

    # 2. Add a project and query again
    repo = tmp_path / "sample-app"
    repo.mkdir()
    project_service.add_project(repo, name="SampleApp")

    resp2 = mya_agent.converse("cuáles son mis proyectos")
    assert "SampleApp" in resp2
    assert "1 proyecto(s) activo(s)" in resp2

    # 3. Trash query empty
    resp_trash1 = mya_agent.converse("qué hay en la papelera")
    assert "La papelera está vacía" in resp_trash1

    # 4. Move to trash and query trash
    p = project_service.get_project_by_name("SampleApp")
    assert p is not None
    project_service.move_to_trash(p.project_id)

    resp_trash2 = mya_agent.converse("ver papelera")
    assert "SampleApp" in resp_trash2
    assert "repositorios en disco permanecen intactos" in resp_trash2

    # 5. Safety guard on delete request
    resp_del = mya_agent.converse("borra este proyecto")
    assert "yo no ejecuto eliminaciones de proyectos directamente" in resp_del
    assert "tus archivos en disco nunca se borran" in resp_del


def test_projects_screen_init_and_refresh(project_service, tmp_path: Path):
    session = create_session(tmp_path)
    screen = ProjectsScreen(session=session, service=project_service)
    assert screen.view_trash is False
    assert screen.search_query == ""

    # Toggle trash
    screen.action_toggle_trash()
    assert screen.view_trash is True
    screen.action_toggle_trash()
    assert screen.view_trash is False


def test_confirm_permanent_delete_modal():
    proj = Project(
        project_id="test-123",
        name="Deletable",
        path="/tmp/deletable",
        state=ProjectState.TRASHED,
    )
    modal = ConfirmPermanentDeleteModal(proj)
    assert modal.project.name == "Deletable"


@pytest.mark.asyncio
async def test_projects_screen_textual_app(project_service, tmp_path: Path):
    from textual.app import App

    # Add a project
    repo = tmp_path / "textual-demo"
    repo.mkdir()
    project_service.add_project(repo, name="TextualDemo")

    session = create_session(repo)
    screen = ProjectsScreen(session=session, service=project_service)

    class TestApp(App[None]):
        def on_mount(self) -> None:
            self.push_screen(screen)

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert screen.is_mounted
        assert len(screen.query(".project_card")) == 1

        # Test toggle trash
        screen.action_toggle_trash()
        await pilot.pause()
        assert screen.view_trash is True
        assert len(screen.query(".project_card_trashed")) == 0
