"""Tests for Mya dialogue models (questions and answers)."""

import pytest

from myagentos.mya.dialogue import (
    Question,
    QuestionAnswer,
    QuestionBatch,
    QuestionKind,
    QuestionOption,
)


class TestQuestion:
    """Tests for the Question model."""

    def test_choice_question(self) -> None:
        q = Question(
            text="Which authentication provider?",
            kind=QuestionKind.CHOICE,
            affects=["plan", "scope"],
            options=[
                QuestionOption(id="jwt", label="JWT"),
                QuestionOption(id="session", label="Sessions"),
            ],
        )
        assert q.kind == QuestionKind.CHOICE
        assert len(q.options) == 2
        assert q.affects == ["plan", "scope"]
        assert q.required is True

    def test_confirmation_question(self) -> None:
        q = Question(
            text="Should the migration be reversible?",
            kind=QuestionKind.CONFIRMATION,
            affects=["risk"],
        )
        assert q.kind == QuestionKind.CONFIRMATION

    def test_free_text_question(self) -> None:
        q = Question(
            text="Describe the expected behavior.",
            kind=QuestionKind.FREE_TEXT,
            required=False,
        )
        assert q.required is False

    def test_question_has_auto_id(self) -> None:
        q = Question(text="test", kind=QuestionKind.CONFIRMATION)
        assert len(q.question_id) == 8

    def test_question_is_frozen(self) -> None:
        q = Question(text="test", kind=QuestionKind.CONFIRMATION)
        with pytest.raises(Exception):
            setattr(q, "text", "modified")


class TestQuestionBatch:
    """Tests for grouped questions (§11)."""

    def test_batch_groups_questions(self) -> None:
        batch = QuestionBatch(
            questions=[
                Question(text="Q1", kind=QuestionKind.CHOICE),
                Question(text="Q2", kind=QuestionKind.CONFIRMATION),
            ],
            context="I need 2 decisions before proceeding.",
        )
        assert len(batch.questions) == 2
        assert batch.context is not None


class TestQuestionAnswer:
    """Tests for the QuestionAnswer model."""

    def test_text_answer(self) -> None:
        answer = QuestionAnswer(question_id="q1", answer="Use JWT")
        assert answer.answer == "Use JWT"
        assert answer.selected_option_id is None

    def test_option_answer(self) -> None:
        answer = QuestionAnswer(
            question_id="q1",
            answer="JWT",
            selected_option_id="jwt",
        )
        assert answer.selected_option_id == "jwt"
