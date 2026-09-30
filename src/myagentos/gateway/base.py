"""Base interface and message structures for Model Gateway adapters (§17.1)."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    """Normalized chat message."""

    model_config = ConfigDict(frozen=True)

    role: str  # "system", "user", "assistant"
    content: str


class LLMResponse(BaseModel):
    """Normalized LLM generation response with token usage metrics."""

    model_config = ConfigDict(frozen=True)

    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""


class ProviderAdapter(ABC):
    """Interface implemented by each model provider connector (Zone Z2, §17.1)."""

    @abstractmethod
    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Synchronously calls provider API to generate response."""
        ...
