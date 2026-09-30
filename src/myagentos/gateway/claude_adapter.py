"""Anthropic Claude API connector adapter implementing structured output (§17.1)."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
from anthropic import omit
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam
from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter


class ClaudeAdapter(ProviderAdapter):
    """Adapter for interacting with Anthropic Claude models via official SDK (§17.1)."""

    def __init__(
        self,
        api_key: str | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client = client

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise MyAgentOSError("ANTHROPIC_API_KEY is not set. Cannot invoke ClaudeAdapter.")
        self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        client = self._get_client()

        # Separate system messages from user/assistant messages
        system_prompts: list[str] = [m.content for m in messages if m.role == "system"]
        system_instruction = "\n\n".join(system_prompts) if system_prompts else omit

        formatted_msgs: list[MessageParam] = [
            {"role": "assistant" if m.role == "assistant" else "user", "content": m.content}
            for m in messages
            if m.role != "system"
        ]

        if not formatted_msgs:
            formatted_msgs = [{"role": "user", "content": "Hello"}]

        extra_body: dict[str, Any] = {"temperature": temperature}
        in_tok = 0
        out_tok = 0
        raw_content = ""

        if response_schema is not None:
            tool_name = "record_structured_output"
            tools: list[ToolParam] = [
                {
                    "name": tool_name,
                    "description": "Output structured JSON matching schema",
                    "input_schema": response_schema.model_json_schema(),
                }
            ]
            tool_choice: ToolChoiceToolParam = {"type": "tool", "name": tool_name}

            resp = client.messages.create(
                model=model_id,
                max_tokens=4096,
                system=system_instruction,
                messages=formatted_msgs,
                tools=tools,
                tool_choice=tool_choice,
                extra_body=extra_body,
            )

            for block in resp.content:
                if getattr(block, "type", "") == "tool_use":
                    raw_content = json.dumps(getattr(block, "input", {}))
                    break
            if not raw_content:
                raw_content = "".join(
                    getattr(b, "text", "") for b in resp.content if hasattr(b, "text")
                )
        else:
            resp = client.messages.create(
                model=model_id,
                max_tokens=4096,
                system=system_instruction,
                messages=formatted_msgs,
                extra_body=extra_body,
            )
            raw_content = "".join(
                getattr(b, "text", "") for b in resp.content if hasattr(b, "text")
            )

        if resp.usage:
            in_tok = resp.usage.input_tokens
            out_tok = resp.usage.output_tokens

        return LLMResponse(
            content=raw_content,
            tool_calls=[],
            input_tokens=in_tok,
            output_tokens=out_tok,
            model_id=model_id,
        )
