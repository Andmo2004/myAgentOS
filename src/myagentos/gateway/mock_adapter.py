"""Mock provider adapter for reproducible and offline testing (§17.1)."""

import html
import re
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
            content = self._default_conversational_response(messages)

        return LLMResponse(
            content=content,
            tool_calls=[],
            input_tokens=len(full_prompt.split()),
            output_tokens=len(content.split()),
            model_id=model_id,
        )

    @staticmethod
    def _default_conversational_response(messages: list[LLMMessage]) -> str:
        """Return a deterministic response based on the latest user turn and context."""
        latest_user = next(
            (message.content for message in reversed(messages) if message.role == "user"), ""
        )
        lower = latest_user.lower()
        context = "\n".join(message.content for message in messages if message.role == "system")
        project_names = re.findall(r"(?m)^- name: ([^;\n]+)", context)
        project_count_match = re.search(r"(?m)^## Registered projects \((\d+)\)", context)
        project_count = (
            int(project_count_match.group(1)) if project_count_match else len(project_names)
        )
        active_block = re.search(r"(?ms)^## Active project\n(.*?)(?=^## |\Z)", context)
        project_registry_unavailable = "Project registry: unavailable" in context
        current_job = re.search(r"(?m)^Current session job: (.+)$", context)
        active_name = "unavailable"
        active_tags = ""
        active_languages = ""
        active_state = ""
        trashed_names = re.findall(r"(?m)^- name: ([^;\n]+); state: trashed", context)
        trash_available = "## Trashed projects (" in context
        trash_empty = "Trash is empty" in context
        if active_block:
            active_name = re.search(r"(?m)^name: (.+)$", active_block.group(1))
            active_state = re.search(r"(?m)^project_state: (.+)$", active_block.group(1))
            active_tags = re.search(r"(?m)^tags: (.+)$", active_block.group(1))
            active_languages = re.search(r"(?m)^languages: (.+)$", active_block.group(1))
            active_name = active_name.group(1) if active_name else "unavailable"
            active_state = active_state.group(1) if active_state else ""
            active_tags = active_tags.group(1) if active_tags else ""
            active_languages = active_languages.group(1) if active_languages else ""

        memory_records = re.findall(
            r'<memory scope="(user|project|session)"[^>]*>(.*?)</memory>',
            context,
            re.DOTALL,
        )
        scoped_memory = [(scope, html.unescape(content)) for scope, content in memory_records]

        if any(
            term in lower
            for term in ("acabamos", "decidimos", "hace un momento", "según lo anterior")
        ):
            session_notes = [content for scope, content in scoped_memory if scope == "session"]
            if session_notes:
                return f"En esta conversación quedó anotado: {session_notes[-1]}"

        if "papelera" in lower or "trash" in lower:
            if not trash_available:
                return "No puedo consultar la papelera en este momento."
            if trash_empty:
                return "La papelera está vacía."
            names = ", ".join(trashed_names)
            return f"En la papelera están: {names}. Los repositorios en disco permanecen intactos."

        if any(
            term in lower
            for term in ("borra este proyecto", "elimina este proyecto", "delete this project")
        ):
            return (
                "Por seguridad, yo no ejecuto eliminaciones de proyectos directamente. "
                "Gestiona su ciclo de vida desde Project Manager; tus archivos en disco "
                "nunca se borran."
            )

        if any(term in lower for term in ("preferencia", "prefiero", "idioma", "cómo prefiero")):
            user_notes = [content for scope, content in scoped_memory if scope == "user"]
            if user_notes:
                return f"Según tu preferencia guardada: {user_notes[0]}"

        if any(
            term in lower
            for term in ("pendiente", "por hacer", "tareas", "backlog", "jobs abiertos")
        ):
            job_note = (
                f" La sesión tiene asociado el job {current_job.group(1)}, "
                "pero no puedo verificar su estado."
                if current_job and current_job.group(1) != "none"
                else ""
            )
            project_note = (
                f" Sí tengo {len(project_names)} proyectos registrados."
                if not project_registry_unavailable
                else " El registro de proyectos tampoco está disponible."
            )
            return (
                "No tengo un backlog de tareas ni un listado de jobs abiertos "
                "disponible ahora mismo."
                f"{job_note}{project_note}"
            )
        if "segundo" in lower or "segunda" in lower:
            dialogue = [message for message in messages if message.role in {"user", "assistant"}]
            has_project_history = any(
                "proyecto" in message.content.lower() for message in dialogue[:-1]
            )
            if has_project_history and len(project_names) >= 2:
                return f"El segundo proyecto registrado es {project_names[1]}."
            return "No tengo una referencia previa suficiente para saber cuál sería el segundo."
        if "proyecto" in lower or "projects" in lower:
            if project_registry_unavailable and not any(
                term in lower
                for term in (
                    "activo",
                    "actual",
                    "este proyecto",
                    "esta aplicación",
                    "esta aplicacion",
                )
            ):
                return "No puedo consultar el registro de proyectos en este momento."
            profile_question = any(
                term in lower
                for term in (
                    "tipo",
                    "stack",
                    "categoriza",
                    "tags",
                    "tecnolog",
                )
            )
            active_project_question = profile_question or any(
                term in lower
                for term in (
                    "activo",
                    "actual",
                    "este proyecto",
                    "esta aplicación",
                    "esta aplicacion",
                )
            )
            if active_project_question:
                if active_name != "unavailable":
                    details = f"; etiquetas: {active_tags}" if active_tags else ""
                    stack = f"; lenguajes: {active_languages}" if active_languages else ""
                    if profile_question:
                        return (
                            f"El proyecto activo {active_name} tiene este perfil{details}{stack}."
                        )
                    state = f" ({active_state})" if active_state else ""
                    return f"El proyecto activo es {active_name}{state}{details}{stack}."
                return "No tengo identificado un proyecto activo en la sesión actual."
            if not project_names:
                return "No tienes ningún proyecto registrado ahora mismo."
            active_note = f" El activo es {active_name}." if active_name != "unavailable" else ""
            project_word = "proyecto registrado" if project_count == 1 else "proyectos registrados"
            return f"Tengo {project_count} {project_word}: {', '.join(project_names)}.{active_note}"
        query_terms = {
            token
            for token in re.findall(r"[\w-]+", lower)
            if len(token) > 3
            and token not in {"este", "esta", "para", "sobre", "como", "qué", "que"}
        }
        for scope in ("session", "project", "user"):
            scoped_matches = [
                content
                for record_scope, content in scoped_memory
                if record_scope == scope
                and query_terms.intersection(set(re.findall(r"[\w-]+", content.lower())))
            ]
            if scoped_matches:
                return f"Según el contexto disponible: {scoped_matches[0]}"
        if any(term in lower for term in ("contexto", "sabes del", "sabes sobre", "qué sabes")):
            if active_name != "unavailable":
                return f"Tengo contexto del proyecto activo {active_name}."
            return "No tengo un proyecto activo identificado en el contexto actual."
        if lower.strip(" ¡!.,¿?") in {
            "hola",
            "hola mya",
            "buenas",
            "hello",
            "hi",
            "hey",
        }:
            return "Hola. ¿Qué tienes en mente?"
        if lower.strip(" ¡!.,¿?") in {"gracias", "muchas gracias", "thanks", "thank you"}:
            return "De nada."
        if any(term in lower for term in ("quién eres", "quien eres", "who are you")):
            return "Soy Mya, la interfaz conversacional de Agentic OS."
        if latest_user.endswith(("?", "؟")) or latest_user.startswith("¿"):
            return "No tengo ese dato en el contexto actual."
        return "Entendido."
