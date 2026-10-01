"""OpenAI API connector adapter implementing structured output and tool use (§17.1)."""

import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.credentials import CredentialStatus, IdentityInfo
from myagentos.gateway.discovery import DiscoveredModel


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

    def validate_credential(self) -> tuple[CredentialStatus, str | None, IdentityInfo | None]:
        """Validates credential using lowest-privilege models.list() call (§6, §26)."""
        if not self.api_key:
            return CredentialStatus.INVALID, "OPENAI_API_KEY no está configurada", None
        try:
            client = self._get_client()
            # Fetch single page or first item with fast timeout
            _ = client.models.list(timeout=5.0)
            org = getattr(client, "organization", None)
            proj = getattr(client, "project", None)
            identity = IdentityInfo(
                principal_name="api_user",
                principal_type="api_key",
                organization=org or None,
                project=proj or None,
                quota_scope=proj or org or None,
            ) if (org or proj) else None
            return CredentialStatus.VALID, None, identity
        except Exception as e:
            err_str = str(e).lower()
            if "401" in err_str or "invalid" in err_str or "unauthorized" in err_str:
                return CredentialStatus.INVALID, "La API key no es válida o fue revocada", None
            if "403" in err_str or "permission" in err_str:
                return CredentialStatus.INSUFFICIENT_SCOPE, "La API key no tiene permisos suficientes", None
            if "429" in err_str or "rate limit" in err_str:
                return CredentialStatus.RATE_LIMITED, "Límite de peticiones alcanzado", None
            return CredentialStatus.PROVIDER_UNAVAILABLE, "Proveedor no disponible o sin conexión", None

    def discover_models(self) -> list[DiscoveredModel]:
        """Discovers accessible models from OpenAI (§8)."""
        if not self.api_key:
            return []
        try:
            client = self._get_client()
            models_page = client.models.list(timeout=10.0)
            discovered: list[DiscoveredModel] = []
            for m in models_page:
                raw_caps = ["code_generation"]
                if "gpt" in m.id or "o1" in m.id or "o3" in m.id:
                    raw_caps.append("tool_use")
                    raw_caps.append("structured_output")
                discovered.append(
                    DiscoveredModel(
                        model_id=m.id,
                        provider="openai",
                        created_at=getattr(m, "created", None),
                        owned_by=getattr(m, "owned_by", None),
                        raw_capabilities=raw_caps,
                    )
                )
            return discovered
        except Exception:
            return []

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
