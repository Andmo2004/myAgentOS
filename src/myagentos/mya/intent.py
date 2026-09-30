"""UserIntent: the structured object Mya produces from natural language.

Mya interprets. Job Controller governs. Policy Engine authorizes.
Workers execute. Verification Guard verifies.

The UserIntent is Mya's only output to the core system.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class IntentMode(StrEnum):
    """Requested execution mode from the user."""

    INTERACTIVE = "interactive"
    AUTONOMOUS = "autonomous"
    NON_INTERACTIVE = "non_interactive"


class UserIntent(BaseModel):
    """Structured representation of what the user wants.

    This is the single artifact Mya produces. It flows into the
    Job Controller, which decides routing, planning, and execution.
    Mya never bypasses this contract.
    """

    model_config = ConfigDict(frozen=True)

    objective: str
    constraints: list[str] = Field(default_factory=list)
    acceptance_hints: list[str] = Field(default_factory=list)
    repository_scope: str | None = None
    requested_mode: IntentMode = IntentMode.INTERACTIVE
    unresolved_questions: list[str] = Field(default_factory=list)


class InterpretResult(BaseModel):
    """Result of Mya interpreting user input.

    Either a resolved intent ready for the Job Controller,
    or a set of questions that need user answers first.
    """

    model_config = ConfigDict(frozen=True)

    resolved: bool = False
    intent: UserIntent | None = None
    questions: list[str] = Field(default_factory=list)
    explanation: str | None = None
