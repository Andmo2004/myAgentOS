"""Google Gemini API connector adapter implementing structured output (§17.1)."""

import os

from google import genai
from google.genai import types
from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter


class GeminiAdapter(ProviderAdapter):
    """Adapter for interacting with Google Gemini models via google-genai SDK."""

    def __init__(self, api_key: str | None = None, client: genai.Client | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self._client = client

    def _get_client(self) -> genai.Client:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise MyAgentOSError("GEMINI_API_KEY or GOOGLE_API_KEY is not set.")
        self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        client = self._get_client()

        # Combine system instructions and user contents
        system_prompts: list[str] = [m.content for m in messages if m.role == "system"]
        conversation = [f"{m.role.upper()}: {m.content}" for m in messages if m.role != "system"]
        contents_text = "\n\n".join(conversation)

        system_instruction: str | None = "\n".join(system_prompts) if system_prompts else None
        response_mime_type: str | None = "application/json" if response_schema is not None else None

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
        )

        response = client.models.generate_content(
            model=model_id,
            contents=contents_text,
            config=config,
        )

        raw_text = response.text or ""
        in_tok = 0
        out_tok = 0
        if response.usage_metadata:
            in_tok = response.usage_metadata.prompt_token_count or 0
            out_tok = response.usage_metadata.candidates_token_count or 0

        return LLMResponse(
            content=raw_text,
            tool_calls=[],
            input_tokens=in_tok,
            output_tokens=out_tok,
            model_id=model_id,
        )
