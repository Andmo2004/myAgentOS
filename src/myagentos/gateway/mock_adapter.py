"""Mock provider adapter for reproducible and offline testing (§17.1)."""

from typing import Any

from pydantic import BaseModel

from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.credentials import CredentialStatus, IdentityInfo
from myagentos.gateway.discovery import DiscoveredModel


class MockProviderAdapter(ProviderAdapter):
    """Deterministic adapter returning pre-configured responses for unit and integration testing."""

    def __init__(self) -> None:
        self.preset_responses: dict[str, str] = {}
        self.call_history: list[list[LLMMessage]] = []
        self.preset_credential_status: CredentialStatus = CredentialStatus.VALID
        self.preset_error_message: str | None = None
        self.preset_identity: IdentityInfo | None = IdentityInfo(
            principal_name="mock-user",
            principal_type="account",
            organization="mock-org",
            project="local-dev",
            quota_scope="local-dev",
        )
        self.preset_discovered_models: list[DiscoveredModel] = [
            DiscoveredModel(
                model_id="mock-mya",
                provider="mock",
                raw_capabilities=["code_generation", "tool_use", "structured_output"],
            ),
            DiscoveredModel(
                model_id="mock-fast",
                provider="mock",
                raw_capabilities=["code_generation"],
            ),
            DiscoveredModel(
                model_id="mock-reasoning",
                provider="mock",
                raw_capabilities=["reasoning", "structured_output"],
            ),
        ]

    def validate_credential(self) -> tuple[CredentialStatus, str | None, IdentityInfo | None]:
        return self.preset_credential_status, self.preset_error_message, self.preset_identity

    def discover_models(self) -> list[DiscoveredModel]:
        if self.preset_credential_status != CredentialStatus.VALID:
            return []
        return list(self.preset_discovered_models)

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
                if getattr(response_schema, "__name__", "") == "PlanResponseSchema":
                    import json

                    content = json.dumps(
                        {
                            "files_to_modify": ["src/main.py"],
                            "files_to_create": [],
                            "files_to_delete": [],
                            "altered_interfaces": [],
                            "test_specs": [],
                            "preliminary_risk": "LOW",
                            "risk_reasons": ["Mock default plan"],
                            "permissions_requested": {
                                "read": ["**"],
                                "write": ["**"],
                                "execute": ["pytest"],
                            },
                            "impact_summary": "Mock plan execution",
                            "assumptions": [],
                            "data_classification_max": "internal",
                            "rationale": "Automated mock plan",
                        }
                    )
                else:
                    dummy: Any = response_schema.model_construct()
                    content = dummy.model_dump_json()
            except Exception:
                pass
        elif content == "Mock LLM output":
            import json

            content = json.dumps(
                {
                    "thought": "Default mock patch proposal",
                    "propose_patch": {
                        "description": "Mock automated modification",
                        "files": [
                            {
                                "path": "src/main.py",
                                "operation": "MODIFY",
                                "content": "# modified\n",
                            }
                        ],
                    },
                }
            )

        return LLMResponse(
            content=content,
            tool_calls=[],
            input_tokens=len(full_prompt.split()),
            output_tokens=len(content.split()),
            model_id=model_id,
        )
