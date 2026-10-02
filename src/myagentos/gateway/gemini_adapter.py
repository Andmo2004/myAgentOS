"""Google Gemini API connector adapter implementing structured output (§17.1)."""

import os

from google import genai
from google.genai import types
from pydantic import BaseModel

from myagentos.core.errors import MyAgentOSError
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.credentials import CredentialStatus, IdentityInfo
from myagentos.gateway.discovery import DiscoveredModel


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

    def validate_credential(self) -> tuple[CredentialStatus, str | None, IdentityInfo | None]:
        """Validates Google Gemini credential using models.list() (§6, §26)."""
        if not self.api_key:
            return (
                CredentialStatus.INVALID,
                "GEMINI_API_KEY o GOOGLE_API_KEY no está configurada",
                None,
            )
        try:
            client = self._get_client()
            pager = client.models.list(config={"page_size": 1})
            for _ in pager:
                break
            return CredentialStatus.VALID, None, None
        except Exception as e:
            err_str = str(e).lower()
            if (
                "401" in err_str
                or "api_key_invalid" in err_str
                or "invalid" in err_str
                or "unauthorized" in err_str
            ):
                return CredentialStatus.INVALID, "La API key no es válida o fue revocada", None
            if "403" in err_str or "permission" in err_str:
                return (
                    CredentialStatus.INSUFFICIENT_SCOPE,
                    "La API key no tiene permisos suficientes",
                    None,
                )
            if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                return CredentialStatus.RATE_LIMITED, "Límite de cuota o peticiones alcanzado", None
            return (
                CredentialStatus.PROVIDER_UNAVAILABLE,
                "Proveedor no disponible o sin conexión",
                None,
            )

    def discover_models(self) -> list[DiscoveredModel]:
        """Discovers accessible models from Google Gemini (§8)."""
        if not self.api_key:
            return []
        try:
            client = self._get_client()
            pager = client.models.list(config={"page_size": 100})
            discovered: list[DiscoveredModel] = []
            for m in pager:
                name = m.name or ""
                clean_id = name.replace("models/", "") if name.startswith("models/") else name
                raw_caps = ["code_generation"]
                if "gemini" in clean_id:
                    raw_caps.extend(["tool_use", "structured_output"])
                discovered.append(
                    DiscoveredModel(
                        model_id=clean_id,
                        provider="gemini",
                        display_name=getattr(m, "display_name", None),
                        owned_by="google",
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
