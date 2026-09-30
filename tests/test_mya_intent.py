"""Tests for Mya UserIntent and InterpretResult models."""

import pytest

from myagentos.mya.intent import IntentMode, InterpretResult, UserIntent


class TestUserIntent:
    """Tests for the UserIntent model."""

    def test_create_minimal_intent(self) -> None:
        intent = UserIntent(objective="fix failing tests")
        assert intent.objective == "fix failing tests"
        assert intent.constraints == []
        assert intent.acceptance_hints == []
        assert intent.repository_scope is None
        assert intent.requested_mode == IntentMode.INTERACTIVE
        assert intent.unresolved_questions == []

    def test_create_full_intent(self) -> None:
        intent = UserIntent(
            objective="add GitHub authentication",
            constraints=["do not modify existing login flow", "use OAuth2"],
            acceptance_hints=["users can log in with GitHub", "existing tests still pass"],
            repository_scope="src/auth/",
            requested_mode=IntentMode.AUTONOMOUS,
            unresolved_questions=[],
        )
        assert intent.objective == "add GitHub authentication"
        assert len(intent.constraints) == 2
        assert len(intent.acceptance_hints) == 2
        assert intent.repository_scope == "src/auth/"
        assert intent.requested_mode == IntentMode.AUTONOMOUS

    def test_intent_is_frozen(self) -> None:
        intent = UserIntent(objective="test")
        with pytest.raises(Exception):
            setattr(intent, "objective", "modified")

    def test_intent_serialization(self) -> None:
        intent = UserIntent(
            objective="refactor payment module",
            constraints=["keep API stable"],
        )
        data = intent.model_dump()
        assert data["objective"] == "refactor payment module"
        assert data["constraints"] == ["keep API stable"]
        restored = UserIntent.model_validate(data)
        assert restored == intent


class TestInterpretResult:
    """Tests for the InterpretResult model."""

    def test_resolved_result(self) -> None:
        intent = UserIntent(objective="fix tests")
        result = InterpretResult(resolved=True, intent=intent)
        assert result.resolved is True
        assert result.intent is not None
        assert result.questions == []

    def test_unresolved_result_with_questions(self) -> None:
        result = InterpretResult(
            resolved=False,
            questions=["Which authentication provider?", "Should it replace existing login?"],
            explanation="I need two decisions before proceeding.",
        )
        assert result.resolved is False
        assert result.intent is None
        assert len(result.questions) == 2

    def test_result_is_frozen(self) -> None:
        result = InterpretResult(resolved=True)
        with pytest.raises(Exception):
            setattr(result, "resolved", False)
