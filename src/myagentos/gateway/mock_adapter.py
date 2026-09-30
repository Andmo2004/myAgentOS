"""Mock provider adapter for reproducible and offline testing (§17.1)."""

from typing import Any

from pydantic import BaseModel

from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter


class MockProviderAdapter(ProviderAdapter):
    """Deterministic adapter returning pre-configured responses for unit and integration testing."""

    def __init__(self) -> None:
        self.preset_responses: dict[str, str] = {}
        self.call_history: list[list[LLMMessage]] = []

    def set_response(self, prompt_keyword: str, response: str) -> None:
        self.preset_responses[prompt_keyword] = response

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        self.call_history.append(messages)

        full_prompt = " ".join(m.content for m in messages)

        # Match preset keywords
        content = "Mock LLM output"
        for kw, resp in self.preset_responses.items():
            if kw in full_prompt:
                content = resp
                break

        # If schema is expected and preset is empty, try default schema instantiation
        if response_schema and content == "Mock LLM output":
            try:
                # Attempt default dummy schema instance
                dummy: Any = response_schema.model_construct()
                content = dummy.model_dump_json()
            except Exception:
                pass

        return LLMResponse(
            content=content,
            tool_calls=[],
            input_tokens=len(full_prompt.split()),
            output_tokens=len(content.split()),
            model_id=model_id,
        )
