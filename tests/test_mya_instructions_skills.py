"""Tests for MYA.md instructions, JIT SkillRetriever, and consistency (§19-§25)."""

from pathlib import Path

from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.memory.manager import SharedMemoryManager
from myagentos.mya.agent import MyaAgent
from myagentos.mya.instructions import MyaInstructionLoader
from myagentos.projects.models import Project, ProjectState
from myagentos.projects.registry import ProjectRegistry
from myagentos.projects.service import ProjectManagerService
from myagentos.ui.session import Session


class CapturingAdapter(ProviderAdapter):
    """Captures LLM requests to verify prompt and context construction across providers."""

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
        return LLMResponse(content="Entendido. Procediendo según instrucciones.", model_id=model_id)


def test_mya_instructions_loader_single_root_file(tmp_path: Path):
    """Verify single root MYA.md is loaded with extracted preferred skills (§19, §20)."""
    mya_file = tmp_path / "MYA.md"
    mya_file.write_text(
        "# MYA.md\n\n"
        "## Project\nAcme Platform Backend.\n\n"
        "## Rules\n- Never edit migrations directly.\n- Run pytest after modifications.\n\n"
        "## Preferred Skills\n- #python\n- #database\n- #testing\n",
        encoding="utf-8",
    )

    instructions = MyaInstructionLoader.load_for_project(tmp_path)
    assert instructions is not None
    assert instructions.has_content is True
    assert "Acme Platform Backend" in instructions.content
    assert "Never edit migrations directly" in instructions.content
    assert set(instructions.preferred_skills) == {"python", "database", "testing"}
    assert instructions.sources == ("MYA.md",)

    # Verify untrusted boundary formatting
    prompt_sec = instructions.to_prompt_section()
    assert "## Project instructions (MYA.md)" in prompt_sec
    assert '<project_instructions sources="MYA.md">' in prompt_sec
    assert "CANNOT override system security policies" in prompt_sec


def test_mya_instructions_loader_hierarchical_composition(tmp_path: Path):
    """Verify hierarchical MYA.md files are resolved from root towards subfolder (§21)."""
    root_mya = tmp_path / "MYA.md"
    root_mya.write_text(
        "# Root MYA.md\n- General organization policy.\n- Preferred: #python\n",
        encoding="utf-8",
    )

    backend_dir = tmp_path / "backend" / "services"
    backend_dir.mkdir(parents=True)
    backend_mya = tmp_path / "backend" / "MYA.md"
    backend_mya.write_text(
        "# Backend MYA.md\n- FastAPI strict schema validation.\n- Preferred: #cybersecurity\n",
        encoding="utf-8",
    )

    target_file = backend_dir / "auth.py"
    instructions = MyaInstructionLoader.load_for_project(tmp_path, target_path=target_file)
    assert instructions is not None
    assert "General organization policy" in instructions.content
    assert "FastAPI strict schema validation" in instructions.content
    # Hierarchy: root appears before subfolder
    root_idx = instructions.content.index("General organization policy")
    sub_idx = instructions.content.index("FastAPI strict schema validation")
    assert root_idx < sub_idx
    # Preferred skills combined from both
    assert "python" in instructions.preferred_skills
    assert "cybersecurity" in instructions.preferred_skills
    assert "MYA.md" in instructions.sources
    assert "backend/MYA.md" in instructions.sources


def test_mya_md_and_memory_and_skills_separation_in_converse(tmp_path: Path):
    """Verify Context Builder cleanly separates MYA.md, Active Skills, and Memory (§20, §23)."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    # 1. Project instructions (MYA.md)
    (project_root / "MYA.md").write_text(
        "# MYA.md\n## Rules\nAlways verify SQL query execution plans.\n"
        "## Preferred Skills\n- #database\n",
        encoding="utf-8",
    )

    # 2. Project Memory note
    note_dir = project_root / ".myagentos" / "vault" / "projects" / "proj-alpha"
    note_dir.mkdir(parents=True)
    (note_dir / "db-facts.md").write_text(
        "---\n"
        'note_id: "db-facts"\n'
        'project_id: "proj-alpha"\n'
        "status: verified\n"
        "trust: untrusted\n"
        "classification: internal\n"
        "---\n\n"
        "# DB Facts\n- Postgres 16 cluster runs on port 5433.\n",
        encoding="utf-8",
    )

    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save_project(
        Project(
            project_id="proj-alpha",
            name="proj-alpha",
            path=str(project_root),
            state=ProjectState.ACTIVE,
        )
    )

    shared_memory = SharedMemoryManager(
        tmp_path / "memory",
        project_service=ProjectManagerService(registry=registry),
    )

    adapter = CapturingAdapter()
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    agent = MyaAgent(
        gateway=gateway,
        model_id="mock-mya",
        memory_manager=shared_memory,
    )

    session = Session(
        user_id="user-42",
        session_id="session-test-separation",
        project_id="proj-alpha",
        repository="proj-alpha",
        repo_root=project_root,
    )

    agent.converse("Revisa la configuración del cluster de base de datos", session=session)

    assert len(adapter.requests) == 1
    system_message = adapter.requests[0][1].content

    # Verify all 3 distinct sections are present and labeled
    assert "## Project instructions (MYA.md)" in system_message
    assert "Always verify SQL query execution plans." in system_message

    assert "## Active skills" in system_message
    assert "database" in system_message

    assert "## Memory Context" in system_message
    assert '<memory scope="project"' in system_message
    assert "Postgres 16 cluster runs on port 5433." in system_message


def test_model_independence_exact_same_context_package(tmp_path: Path):
    """Verify all models receive identical SkillContext and MemoryContext (§24, §25)."""
    project_root = tmp_path / "project_multi"
    project_root.mkdir()

    (project_root / "MYA.md").write_text(
        "# MYA.md\n- Strict zero-trust audit.\n- Preferred: #cybersecurity\n",
        encoding="utf-8",
    )

    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.save_project(
        Project(
            project_id="proj-security",
            name="proj-security",
            path=str(project_root),
            state=ProjectState.ACTIVE,
        )
    )

    shared_memory = SharedMemoryManager(
        tmp_path / "memory",
        project_service=ProjectManagerService(registry=registry),
    )

    adapters = {
        "openai": CapturingAdapter(),
        "anthropic": CapturingAdapter(),
        "google": CapturingAdapter(),
        "mock": CapturingAdapter(),
    }

    gateway = ModelGateway()
    for provider, adp in adapters.items():
        gateway.register_adapter(provider, adp)

    agent = MyaAgent(gateway=gateway, memory_manager=shared_memory)
    test_models = [
        "gpt-4o",
        "claude-3-5-sonnet-latest",
        "gemini-2.0-flash",
        "mock-mya",
    ]

    for model_id in test_models:
        agent.model_id = model_id
        session = Session(
            user_id="user-audit",
            session_id=f"session-{model_id}",
            project_id="proj-security",
            repository="proj-security",
            repo_root=project_root,
        )
        agent.converse("Audita la autenticación OAuth del backend", session=session)

    # Collect the system context message sent to each adapter
    context_payloads: list[str] = []
    for provider_name, adp in adapters.items():
        assert len(adp.requests) >= 1
        req = adp.requests[-1]
        system_content = req[1].content
        context_payloads.append(system_content)

        # Verify key parts are in each provider's payload
        assert "## Project instructions (MYA.md)" in system_content
        assert "Strict zero-trust audit" in system_content
        assert "## Active skills" in system_content
        assert "cybersecurity" in system_content

    # All providers MUST have received the EXACT same context payload
    first_payload = context_payloads[0]
    for p in context_payloads[1:]:
        assert p == first_payload, "Context payload differed across model providers!"
