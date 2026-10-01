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

    def validate_credential(self) -> tuple[Any, str | None, Any | None]:
        """Validates credential using lowest-privilege read-only operation (§6, §26).

        Returns:
            tuple of (CredentialStatus, error_message or None, IdentityInfo or None)
        """
        from myagentos.gateway.credentials import CredentialStatus

        return CredentialStatus.UNKNOWN, None, None

    def discover_models(self) -> list[Any]:
        """Discovers accessible models in real time with the active credential (§8, §26)."""
        return []

    def get_identity(self) -> Any | None:
        """Returns non-secret identity metadata if exposed by the provider (§4.3, §20)."""
        _, _, identity = self.validate_credential()
        return identity
