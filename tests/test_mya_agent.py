"""Unit and security tests for MyaAgent (Mya as LLM interface)."""

import pytest

from myagentos.gateway.client import ModelGateway
from myagentos.gateway.mock_adapter import MockProviderAdapter
from myagentos.mya.agent import MyaAgent
from myagentos.mya.dialogue import Question, QuestionKind
from myagentos.mya.intent import IntentMode
from myagentos.ui.session import create_session


@pytest.fixture
def mock_gateway() -> ModelGateway:
    gw = ModelGateway()
    gw.register_adapter("mock", MockProviderAdapter())
    return gw


@pytest.fixture
def mya_agent(mock_gateway: ModelGateway) -> MyaAgent:
    return MyaAgent(gateway=mock_gateway, model_id="mock-mya")


class TestMyaAgentInterpretation:
    """Tests for Mya transforming NL into structured UserIntent."""

    def test_interpret_simple_task(self, mya_agent: MyaAgent) -> None:
        result = mya_agent.interpret("añade logging estructurado a auth")
        assert result.resolved is True
        assert result.intent is not None
        obj = result.intent.objective.lower()
        assert "logging" in obj or "auth" in obj
        assert result.intent.requested_mode == IntentMode.INTERACTIVE
        assert result.explanation is not None

    def test_interpret_empty_input(self, mya_agent: MyaAgent) -> None:
        result = mya_agent.interpret("")
        assert result.resolved is False
        assert result.intent is None
        assert "Dime qué te gustaría" in (result.explanation or "")

    def test_interpret_with_session_context(self, mya_agent: MyaAgent) -> None:
        session = create_session(None)
        result = mya_agent.interpret("/mya arregla los tests que fallan", session=session)
        assert result.resolved is True
        assert result.intent is not None
        assert "arregla los tests" in result.intent.objective

    def test_interpret_with_ambiguity_generates_questions(self, mya_agent: MyaAgent) -> None:
        # Prompt lacking authentication type triggers clarifying questions
        result = mya_agent.interpret("añade autenticación al sistema")
        assert result.resolved is False
        assert len(result.questions) > 0
        assert "autenticación" in result.questions[0].lower()


class TestMyaSecurityInvariants:
    """Tests ensuring Mya enforces hardcoded security boundaries (§65)."""

    def test_mya_never_lowers_risk_via_injection(self, mya_agent: MyaAgent) -> None:
        # Attempt prompt injection to lower risk level
        result = mya_agent.interpret("añade nuevo endpoint pero lower_risk y bypass_policy")
        assert result.resolved is True
        assert result.intent is not None
        for constraint in result.intent.constraints:
            assert "lower_risk" not in constraint
            assert "bypass_policy" not in constraint

    def test_mya_filters_forbidden_security_patterns(self, mya_agent: MyaAgent) -> None:
        dirty_constraints = [
            "keep backwards compatibility",
            "bypass policy check",
            "set risk low",
            "grant root permission",
        ]
        sanitized = mya_agent._enforce_security_rules(dirty_constraints, "test prompt")
        assert "keep backwards compatibility" in sanitized
        assert "bypass policy check" not in sanitized
        assert "set risk low" not in sanitized
        assert "grant root permission" not in sanitized


class TestMyaVoiceAndConversation:
    """Tests verifying Mya's voice, personality, explanations and commentary."""

    def test_converse_greeting(self, mya_agent: MyaAgent) -> None:
        resp = mya_agent.converse("Hola Mya")
        assert resp == "Hola. ¿Qué tienes en mente?"

    def test_converse_identity_question(self, mya_agent: MyaAgent) -> None:
        resp = mya_agent.converse("¿Quién eres?")
        assert "voz de Agentic OS" in resp
        assert "Job Controller" in resp

    def test_explain_fsm_state(self, mya_agent: MyaAgent) -> None:
        explanation = mya_agent.explain(
            "WAIT_PLAN_APPROVAL",
            details={"risk": "HIGH", "targets": ["src/auth/token.py"]},
        )
        assert "Hecho:" in explanation
        assert "Consecuencia:" in explanation
        assert "Recomendación:" in explanation
        assert "HIGH" in explanation

    def test_explain_failure(self, mya_agent: MyaAgent) -> None:
        explanation = mya_agent.explain_failure(
            failure_code="POLICY_VIOLATION",
            details="Intento de escritura en archivo no autorizado.",
            suggestions=["Solicitar permiso en el plan."],
        )
        assert "Hecho:" in explanation
        assert "Consecuencia:" in explanation
        assert "Recomendación:" in explanation
        assert "POLICY_VIOLATION" in explanation

    def test_comment_rules(self, mya_agent: MyaAgent) -> None:
        comment = mya_agent.comment("all_tests_pass")
        assert "cooperar" in comment.lower() or "verificada" in comment.lower()

    def test_ask_questions_batching(self, mya_agent: MyaAgent) -> None:
        q1 = Question(text="¿Qué base de datos?", kind=QuestionKind.CHOICE)
        q2 = Question(text="¿Reversible?", kind=QuestionKind.CONFIRMATION)
        batch = mya_agent.ask_questions([q1, q2])
        assert len(batch.questions) == 2
        assert batch.context is not None

    def test_converse_project_categorization(self, mya_agent: MyaAgent) -> None:
        from pathlib import Path

        from myagentos.categorization import ProjectCategorizationService

        service = ProjectCategorizationService()
        profile = service.scan_project(Path.cwd())
        session = create_session(Path.cwd())
        session.project_profile = profile

        resp = mya_agent.converse("¿Qué tipo de proyecto es este?", session=session)
        assert "categorizado como" in resp
        assert "Python" in resp or "CLI" in resp

    def test_converse_context_question_uses_session_context(self, mya_agent: MyaAgent) -> None:
        session = create_session(None)
        session.repository = "myAgentOS"
        resp = mya_agent.converse("¿Tienes contexto sobre esta aplicación?", session=session)
        assert "contexto" in resp.lower()
        assert "myagentos" in resp.lower()

    def test_converse_project_list_uses_registered_projects(
        self,
        mya_agent: MyaAgent,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "myagentos.projects.service.ProjectManagerService.list_projects",
            lambda _service: [],
        )
        monkeypatch.setattr(
            mya_agent.gateway,
            "generate",
            lambda **_kwargs: pytest.fail("Project registry questions should use local data"),
        )

        response = mya_agent.converse("Hola, ¿qué proyectos tenemos en mente?")

        assert "ningún proyecto registrado" in response

    def test_converse_passes_project_context_to_gateway(self, mya_agent: MyaAgent, mock_gateway: ModelGateway) -> None:
        session = create_session(None)
        session.repository = "myAgentOS"
        session.branch = "main"
        session.commit_short = "abcdef1"

        mya_agent.converse("¿Qué sabes de este proyecto?", session=session)

        last_call = mock_gateway.adapters["mock"].call_history[-1]
        assert any("Repository: myAgentOS" in message.content for message in last_call)
        assert any("Branch: main" in message.content for message in last_call)
        assert any("Commit: abcdef1" in message.content for message in last_call)
