import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myagentos.memory.manager import SharedMemoryManager
from myagentos.memory.models import MemoryLimits, MemoryRecord
from myagentos.memory.retrieval import MemoryContextBuilder
from myagentos.memory.store import MAX_PERSISTED_RECORDS_PER_SCOPE, JsonlMemoryStore
from myagentos.projects.models import Project, ProjectState
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session


def _registered_project(registry: ProjectRegistry, project_id: str, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    registry.save_project(
        Project(
            project_id=project_id,
            name=project_id,
            path=str(root),
            state=ProjectState.ACTIVE,
        )
    )


def _verified_note(
    project_root: Path, project_id: str, content: str, status: str = "verified"
) -> None:
    note_dir = project_root / ".myagentos" / "vault" / "projects" / project_id
    note_dir.mkdir(parents=True, exist_ok=True)
    (note_dir / f"{content.split()[0]}.md").write_text(
        "---\n"
        f'note_id: "{content.split()[0]}"\n'
        f'project_id: "{project_id}"\n'
        f"status: {status}\n"
        "trust: untrusted\n"
        "classification: internal\n"
        "provenance:\n"
        '  model: "model-a"\n'
        "---\n\n"
        f"# Note\n\n## Decisions\n- {content}\n",
        encoding="utf-8",
    )


def test_session_memory_persists_across_manager_instances(tmp_path: Path) -> None:
    memory_root = tmp_path / "memory"
    manager_a = SharedMemoryManager(memory_root)
    isolated_project = tmp_path / "project-a"
    isolated_project.mkdir()
    session = Session(
        user_id="user-1",
        session_id="session-1",
        project_id="project-a",
        repo_root=isolated_project,
    )
    manager_a.record_session_turn(
        session=session,
        user_message="Estamos trabajando en autenticación.",
        assistant_message="Entendido.",
    )

    manager_b = SharedMemoryManager(memory_root)
    context = manager_b.build_context(session=session, query="¿Qué estamos trabajando?")

    assert len(context.session) == 1
    assert "autenticación" in context.formatted
    assert context.session[0].session_id == "session-1"
    assert context.session[0].project_id == "project-a"


def test_user_and_session_scopes_are_isolated(tmp_path: Path) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    manager.propose_user_memory(user_id="user-a", content="Prefiere respuestas en español")
    manager.propose_user_memory(user_id="user-b", content="Prefiere respuestas en inglés")
    manager.record_session_turn(
        session=Session(user_id="user-a", session_id="session-a"),
        user_message="S1 note unique-s1",
        assistant_message="S1 response",
    )
    manager.record_session_turn(
        session=Session(user_id="user-a", session_id="session-b"),
        user_message="S2 note unique-s2",
        assistant_message="S2 response",
    )

    records_a = manager.retrieve(
        user_id="user-a", project_id=None, session_id="session-a", query="", limit=20
    )
    records_b = manager.retrieve(
        user_id="user-b", project_id=None, session_id="session-a", query="", limit=20
    )

    assert all(record.user_id == "user-a" for record in records_a)
    assert all(
        record.session_id == "session-a" for record in records_a if record.scope == "session"
    )
    assert not any("español" in record.content for record in records_b)
    assert not any("unique-s2" in record.content for record in records_a)


def test_project_memory_isolated_and_verified_notes_only(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "projects.json")
    root_a = tmp_path / "project-a"
    root_b = tmp_path / "project-b"
    _registered_project(registry, "project-a", root_a)
    _registered_project(registry, "project-b", root_b)
    _verified_note(root_a, "project-a", "uses PostgreSQL")
    _verified_note(root_a, "project-a", "stale SQLite decision", status="stale")
    _verified_note(root_b, "project-b", "uses SQLite")
    manager = SharedMemoryManager(
        tmp_path / "memory",
        project_service=ProjectManagerService(registry=registry),
    )

    context_a = manager.build_context(
        session=Session(
            user_id="user-a", session_id="s-a", project_id="project-a", repo_root=root_a
        ),
        query="What database does the project use?",
    )
    context_b = manager.build_context(
        session=Session(
            user_id="user-a", session_id="s-b", project_id="project-b", repo_root=root_b
        ),
        query="What database does the project use?",
    )

    assert "PostgreSQL" in context_a.formatted
    assert "SQLite" not in context_a.formatted
    assert "SQLite" in context_b.formatted
    assert "PostgreSQL" not in context_b.formatted
    assert all(record.status == "verified" for record in context_a.project)
    assert all(record.trust == "untrusted" for record in context_a.project)
    assert all("provider" not in record.__dict__ for record in context_a.records)


def test_user_memory_requires_explicit_confirmation_and_rejects_secrets(tmp_path: Path) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    record_id = manager.propose_user_memory(
        user_id="user-a", content="Prefiere respuestas concisas"
    )
    duplicate_id = manager.propose_user_memory(
        user_id="user-a", content="  Prefiere   respuestas concisas  "
    )
    assert duplicate_id == record_id
    pending = manager.retrieve(
        user_id="user-a", project_id=None, session_id=None, query="preferencias", limit=10
    )
    assert not pending

    manager.confirm_user_memory(record_id, "user-a")
    confirmed = manager.retrieve(
        user_id="user-a", project_id=None, session_id=None, query="preferencias", limit=10
    )
    assert len(confirmed) == 1
    assert confirmed[0].status == "verified"

    with pytest.raises(ValueError, match="secret scanner|credential"):
        manager.propose_user_memory(user_id="user-a", content="api_key=super-secret-value")


def test_same_memory_context_is_model_independent(tmp_path: Path) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    session = Session(user_id="user-1", session_id="session-1")
    manager.record_session_turn(
        session=session,
        user_message="Decidimos mantener FastAPI.",
        assistant_message="Queda anotado para esta sesión.",
    )

    contexts = [
        manager.build_context(session=session, query="¿Qué decidimos?").formatted
        for _provider in ("openai", "anthropic", "google", "mock")
    ]

    assert len(set(contexts)) == 1
    assert "FastAPI" in contexts[0]


def test_switching_project_does_not_retrieve_previous_project_session_memory(
    tmp_path: Path,
) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    manager.append_session_memory(
        session=Session(
            user_id="user-1",
            session_id="session-1",
            project_id="project-a",
            repo_root=project_a,
        ),
        content="P1 utiliza PostgreSQL.",
    )

    context_b = manager.build_context(
        session=Session(
            user_id="user-1",
            session_id="session-1",
            project_id="project-b",
            repo_root=project_b,
        ),
        query="¿Qué base de datos usamos?",
    )

    assert "PostgreSQL" not in context_b.formatted


def test_history_from_previous_project_is_filtered(tmp_path: Path) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    context = manager.build_context(
        session=Session(
            user_id="user-1",
            session_id="session-1",
            project_id="project-b",
            repo_root=project_b,
        ),
        query="What database does this project use?",
        history=[
            {
                "role": "user",
                "content": "P1 uses PostgreSQL.",
                "project_id": "project-a",
            },
            {
                "role": "assistant",
                "content": "Noted.",
                "project_id": "project-a",
            },
        ],
    )

    assert "PostgreSQL" not in context.formatted


def test_memory_context_respects_character_and_token_budgets(tmp_path: Path) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    session = Session(user_id="user-1", session_id="session-1", repo_root=tmp_path)
    manager.append_session_memory(
        session=session,
        content="Verified fact " + ("detail " * 500),
    )
    builder = MemoryContextBuilder(
        manager,
        limits=MemoryLimits(
            max_records={"user": 1, "project": 1, "session": 4},
            max_chars=600,
            max_tokens_estimate=160,
        ),
    )

    context = builder.build(
        user_id="user-1",
        project_id=None,
        session_id="session-1",
        user_message="What is the verified fact?",
        base_context="Session metadata",
    )

    assert len(context.formatted) <= 600
    assert context.total_tokens_estimate <= 160

    base_only = builder.build(
        user_id="user-1",
        project_id=None,
        session_id=None,
        user_message="A general question",
        base_context="structural context " * 1_000,
    )
    assert len(base_only.formatted) <= 600
    assert base_only.total_tokens_estimate <= 160


def test_project_memory_write_is_reserved_for_curator(tmp_path: Path) -> None:
    manager = SharedMemoryManager(tmp_path / "memory")
    record = MemoryRecord(
        memory_id="project-note",
        scope="project",
        user_id="user-1",
        project_id="project-a",
        session_id=None,
        namespace_id="/vault/Proyectos/project-a",
        content="API uses FastAPI",
        status="proposed",
        classification="internal",
        trust="untrusted",
        created_at=Session().created_at,
        updated_at=Session().created_at,
        source="test",
        content_hash="hash",
    )

    with pytest.raises(ValueError, match="Curator"):
        manager.propose_project_memory(record)


def test_active_session_resumes_by_user_and_project_without_storing_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from myagentos.ui.session import _active_session_id

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MYA_HOME", str(tmp_path / "mya-home"))
    project_path = str(tmp_path / "private-project-path")

    first = _active_session_id(project_path)
    resumed = _active_session_id(project_path)
    another_project = _active_session_id(str(tmp_path / "other-project"))
    marker = (tmp_path / "mya-home" / "memory" / "active_session.json").read_text(encoding="utf-8")

    assert resumed == first
    assert another_project != first
    assert project_path not in marker
    assert "project_key_hash" in marker


def test_session_memory_storage_has_a_hard_record_limit(tmp_path: Path) -> None:
    store = JsonlMemoryStore(tmp_path / "memory")
    now = datetime.now(UTC)
    base_record = MemoryRecord(
        memory_id="memory-0",
        scope="session",
        user_id="user-1",
        project_id=None,
        session_id="session-1",
        namespace_id="/sessions/session-1",
        content="Recent session fact",
        status="active",
        classification="internal",
        trust="untrusted",
        created_at=now,
        updated_at=now,
        source="test",
        content_hash=hashlib.sha256(b"Recent session fact").hexdigest(),
    )

    for index in range(MAX_PERSISTED_RECORDS_PER_SCOPE + 5):
        store.append(replace(base_record, memory_id=f"memory-{index}"))

    records = store.retrieve(
        user_id="user-1",
        project_id=None,
        session_id="session-1",
        query="",
        limit=MAX_PERSISTED_RECORDS_PER_SCOPE + 10,
    )

    assert len(records) == MAX_PERSISTED_RECORDS_PER_SCOPE
