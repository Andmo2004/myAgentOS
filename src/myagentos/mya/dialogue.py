"""Dialogue models for Mya's structured questions and answers.

Mya asks only when missing information that materially changes
scope, risk, plan, or acceptance criteria. Mya prefers to discover
information locally before asking the user.
"""

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class QuestionKind(StrEnum):
    """Type of question determining UI control rendering."""

    CHOICE = "choice"
    CONFIRMATION = "confirmation"
    FREE_TEXT = "free_text"
    SCOPE = "scope"


class QuestionOption(BaseModel):
    """A selectable option for choice-type questions."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str


class Question(BaseModel):
    """A structured question from Mya to the user.

    Each question declares what it affects (plan, risk, scope, data_policy)
    so the UI can explain why the question matters.
    """

    model_config = ConfigDict(frozen=True)

    question_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str
    kind: QuestionKind
    required: bool = True
    affects: list[str] = Field(default_factory=list)
    options: list[QuestionOption] = Field(default_factory=list)


class QuestionAnswer(BaseModel):
    """User's response to a structured question."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    answer: str
    selected_option_id: str | None = None


class QuestionBatch(BaseModel):
    """A grouped set of questions to minimize user turns (§11).

    Mya prefers to ask multiple questions at once rather than
    one question per turn.
    """

    model_config = ConfigDict(frozen=True)

    questions: list[Question]
    context: str | None = None
