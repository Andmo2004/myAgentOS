import re
from pathlib import Path

from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.gateway.mock_adapter import MockProviderAdapter
from myagentos.memory.manager import SharedMemoryManager
from myagentos.mya.agent import MyaAgent
from myagentos.mya.context import ConversationContextService
from myagentos.projects.models import Project, ProjectState
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session


class CapturingAdapter(ProviderAdapter):
    def __init__(self) -> None:
        self.requests: list[list[LLMMessage]] = []

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type | None = None,
    ) -> LLMResponse:
        self.requests.append(messages)
        return LLMResponse(content="ok", model_id=model_id)


def _write_verified_project_note(project_root: Path, project_id: str) -> None:
    note_dir = project_root / ".myagentos" / "vault" / "projects" / project_id
    note_dir.mkdir(parents=True, exist_ok=True)
    (note_dir / "api-framework.md").write_text(
        "---\n"
        'note_id: "api-framework"\n'
        f'project_id: "{project_id}"\n'
        "status: verified\n"
        "trust: untrusted\n"
        "classification: internal\n"
        "provenance:\n"
        '  model: "curator-model-a"\n'
        "---\n\n"
        "# API framework\n\n## Decisions\n- API uses FastAPI.\n",
        encoding="utf-8",
    )


def test_same_project_memory_is_sent_to_each_registered_provider(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save_project(
        Project(
            project_id="project-1",
            name="project-one",
            path=str(project_root),
            state=ProjectState.ACTIVE,
        )
    )
    _write_verified_project_note(project_root, "project-1")
    shared_memory = SharedMemoryManager(
        tmp_path / "memory",
        project_service=ProjectManagerService(registry=registry),
    )
    gateway = ModelGateway()
    adapters = {name: CapturingAdapter() for name in ("openai", "anthropic", "google", "mock")}
    for provider, adapter in adapters.items():
        gateway.register_adapter(provider, adapter)
    agent = MyaAgent(
        gateway=gateway,
        memory_manager=shared_memory,
        conversation_context_service=ConversationContextService(
            project_service=ProjectManagerService(registry=registry)
        ),
    )
    session = Session(
        user_id="user-1",
        session_id="session-1",
        project_id="project-1",
        repository="project-one",
        repo_root=project_root,
    )

    for model_id in ("gpt-4o", "claude-3-5-sonnet-latest", "gemini-2.0-flash", "mock-mya"):
        agent.model_id = model_id
        agent.converse("¿Qué framework usa el API?", session=session)

    project_memory_payloads = []
    for adapter in adapters.values():
        request = adapter.requests[0]
        memory_context = next(
            message.content for message in request if '<memory scope="project"' in message.content
        )
        match = re.search(r'<memory scope="project".*?</memory>', memory_context, re.DOTALL)
        assert match is not None
        context_message = match.group(0)
        project_memory_payloads.append(context_message)
        assert "API uses FastAPI" in context_message
        assert 'trust="untrusted"' in context_message
        assert "curator-model-a" not in context_message
    assert len(set(project_memory_payloads)) == 1


def test_model_switch_keeps_session_memory_in_same_session(tmp_path: Path) -> None:
    shared_memory = SharedMemoryManager(tmp_path / "memory")
    gateway = ModelGateway()
    adapter = CapturingAdapter()
    gateway.register_adapter("mock", adapter)
    agent = MyaAgent(gateway=gateway, memory_manager=shared_memory)
    session = Session(user_id="user-1", session_id="session-stable", repo_root=tmp_path)

    agent.model_id = "mock-first"
    agent.converse("Estamos trabajando en autenticación.", session=session)
    agent.model_id = "mock-second"
    agent.converse("¿Qué acabamos de decidir?", session=session)

    second_context = adapter.requests[1][1].content
    assert "Estamos trabajando en autenticación." in second_context
    assert 'scope="session"' in second_context
    assert adapter.requests[0][0].content == adapter.requests[1][0].content


def test_mock_answers_from_shared_project_and_session_memory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save_project(
        Project(
            project_id="project-1",
            name="project-one",
            path=str(project_root),
            state=ProjectState.ACTIVE,
        )
    )
    _write_verified_project_note(project_root, "project-1")
    memory = SharedMemoryManager(
        tmp_path / "memory",
        project_service=ProjectManagerService(registry=registry),
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", MockProviderAdapter())
    agent = MyaAgent(
        gateway=gateway,
        memory_manager=memory,
        conversation_context_service=ConversationContextService(
            project_service=ProjectManagerService(registry=registry)
        ),
    )
    session = Session(
        user_id="user-1",
        session_id="session-1",
        project_id="project-1",
        repository="project-one",
        repo_root=project_root,
    )

    project_answer = agent.converse("¿Qué framework usa el API?", session=session)
    memory.record_session_turn(
        session=session,
        user_message="Decidimos mantener SQLite en el prototipo.",
        assistant_message="SQLite queda como decisión de esta sesión.",
    )
    session_answer = agent.converse("¿Qué acabamos de decidir?", session=session)

    assert "FastAPI" in project_answer
    assert "SQLite" in session_answer


def test_mock_answers_user_preference_from_confirmed_user_memory(tmp_path: Path) -> None:
    memory = SharedMemoryManager(tmp_path / "memory")
    preference_id = memory.propose_user_memory(
        user_id="user-1",
        content="El usuario prefiere respuestas en español.",
    )
    memory.confirm_user_memory(preference_id, "user-1")
    gateway = ModelGateway()
    gateway.register_adapter("mock", MockProviderAdapter())
    agent = MyaAgent(gateway=gateway, memory_manager=memory)

    response = agent.converse(
        "¿Cuál es mi preferencia de idioma?",
        session=Session(user_id="user-1", session_id="session-1", repo_root=tmp_path),
    )

    assert "español" in response


def test_provider_failure_fallback_uses_verified_project_memory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save_project(
        Project(
            project_id="project-1",
            name="project-one",
            path=str(project_root),
            state=ProjectState.ACTIVE,
        )
    )
    _write_verified_project_note(project_root, "project-1")
    memory = SharedMemoryManager(
        tmp_path / "memory",
        project_service=ProjectManagerService(registry=registry),
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", MockProviderAdapter())
    agent = MyaAgent(
        gateway=gateway,
        memory_manager=memory,
        conversation_context_service=ConversationContextService(
            project_service=ProjectManagerService(registry=registry)
        ),
    )
    agent.model_id = "mock-mya"
    agent.gateway.generate = lambda **_kwargs: (_ for _ in ()).throw(ConnectionError("offline"))
    session = Session(
        user_id="user-1",
        session_id="session-1",
        project_id="project-1",
        repository="project-one",
        repo_root=project_root,
    )

    response = agent.converse("¿Qué framework usa el API?", session=session)

    assert "FastAPI" in response
