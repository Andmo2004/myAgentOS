"""Model Gateway: single authorized egress point to remote LLM providers (Zone Z2, §17)."""

from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.registry import ModelRegistry


class ModelGateway:
    """The Model Gateway regulates all external inference calls in Zone Z2 (§17.1)."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()
        self.adapters: dict[str, ProviderAdapter] = {}

    def register_adapter(self, provider: str, adapter: ProviderAdapter) -> None:
        self.adapters[provider] = adapter

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        provider: str | None = None,
        platform: str = "api",
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Dispatches an inference request through the registered provider adapter (§17.1)."""
        resolved_provider = provider

        # Attempt to resolve from registry
        if not resolved_provider:
            for entry in self.registry._entries.values():
                if entry.model_id == model_id:
                    resolved_provider = entry.provider
                    break

        # Fallback heuristic resolution if not explicitly in registry
        if not resolved_provider:
            if model_id.startswith("mock"):
                resolved_provider = "mock"
            elif model_id.startswith("gpt") or "openai" in model_id:
                resolved_provider = "openai"
            elif "gemini" in model_id:
                resolved_provider = "google"
            else:
                resolved_provider = "mock"

        adapter = self.adapters.get(resolved_provider)
        if adapter is None:
            msg = f"No provider adapter registered for '{resolved_provider}' (model: {model_id})"
            raise MyAgentOSError(msg)

        return adapter.generate(
            messages=messages,
            model_id=model_id,
            temperature=temperature,
            response_schema=response_schema,
        )
