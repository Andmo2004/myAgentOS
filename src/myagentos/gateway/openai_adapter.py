"""OpenAI API connector adapter implementing structured output and tool use (§17.1)."""

import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    """Adapter for interacting with OpenAI API models."""

    def __init__(self, api_key: str | None = None, client: OpenAI | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._client = client

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise MyAgentOSError("OPENAI_API_KEY is not set. Cannot invoke OpenAIAdapter.")
        self._client = OpenAI(api_key=self.api_key)
        return self._client

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        client = self._get_client()

        formatted_msgs: list[dict[str, Any]] = [
            {"role": m.role, "content": m.content} for m in messages
        ]

        in_tok = 0
        out_tok = 0

        if response_schema is not None:
            # Structured output with Pydantic parser
            parsed_completion = client.beta.chat.completions.parse(
                model=model_id,
                messages=formatted_msgs,  # type: ignore[arg-type]
                temperature=temperature,
                response_format=response_schema,
            )
            parsed = parsed_completion.choices[0].message.parsed
            raw_content = parsed.model_dump_json() if parsed else ""
            if parsed_completion.usage:
                in_tok = parsed_completion.usage.prompt_tokens
                out_tok = parsed_completion.usage.completion_tokens
        else:
            chat_completion = client.chat.completions.create(
                model=model_id,
                messages=formatted_msgs,  # type: ignore[arg-type]
                temperature=temperature,
            )
            raw_content = chat_completion.choices[0].message.content or ""
            if chat_completion.usage:
                in_tok = chat_completion.usage.prompt_tokens
                out_tok = chat_completion.usage.completion_tokens

        return LLMResponse(
            content=raw_content,
            tool_calls=[],
            input_tokens=in_tok,
            output_tokens=out_tok,
            model_id=model_id,
        )
