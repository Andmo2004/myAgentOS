"""Mya: conversational LLM agent giving voice and personality to Agentic OS.

Follows the Agentic OS architecture:
Mya (LLM) -> UserIntent -> Job Controller -> Planner / Worker / Reviewer -> Sandbox.

Mya's 5 responsibilities:
1. Conversación (Natural dialogue, guidance, personality)
2. Interpretación (NL -> structured UserIntent)
3. Explicación (Translating system state, failures, diffs: Hecho -> Consecuencia -> Recomendación)
4. Comentarios (Context-aware observations with subtle irony)
5. Preguntas (Structured clarifying questions)

Hardcoded Security Boundary:
Mya NEVER grants capabilities, NEVER lowers risk levels, NEVER approves plans or diffs,
and NEVER executes tools directly. Mya produces UserIntent and hands it to the Job Controller.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway
from myagentos.memory.manager import SharedMemoryManager
from myagentos.memory.models import MemoryContext
from myagentos.mya.context import ConversationContext, ConversationContextService
from myagentos.mya.dialogue import Question, QuestionBatch
from myagentos.mya.explanations import translate_state
from myagentos.mya.intent import IntentMode, InterpretResult, UserIntent
from myagentos.mya.prompts import (
    MYA_CONVERSE_PROMPT,
    MYA_INTERPRET_PROMPT,
)
from myagentos.ui.session import Session

logger = logging.getLogger(__name__)


def _clean_json_text(raw_text: str) -> str:
    """Strips markdown fences and cleans JSON output."""
    clean = raw_text.strip()
    if clean.startswith("```json"):
        clean = clean[len("```json") :].strip()
    elif clean.startswith("```"):
        clean = clean[3:].strip()
    if clean.endswith("```"):
        clean = clean[:-3].strip()
    return clean


class MyaInterpretationSchema(BaseModel):
    """Internal schema for parsing LLM structured interpretation."""

    model_config = ConfigDict(frozen=True)

    objective: str = ""
    constraints: list[str] = Field(default_factory=list)
    acceptance_hints: list[str] = Field(default_factory=list)
    repository_scope: str | None = None
    requested_mode: str = "interactive"
    unresolved_questions: list[str] = Field(default_factory=list)
    commentary: str | None = None


class MyaAgent:
    """The conversational LLM interface for Agentic OS."""

    def __init__(
        self,
        gateway: ModelGateway,
        model_id: str = "mock-mya",
        event_store: EventStore | None = None,
        conversation_context_service: ConversationContextService | None = None,
        memory_manager: SharedMemoryManager | None = None,
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.event_store = event_store
        self.conversation_context_service = (
            conversation_context_service or ConversationContextService()
        )
        self._test_memory_dir: tempfile.TemporaryDirectory[str] | None = None
        if memory_manager is None:
            from myagentos.config.paths import resolve_mya_home

            if os.environ.get("PYTEST_CURRENT_TEST"):
                self._test_memory_dir = tempfile.TemporaryDirectory(prefix="myagentos-test-memory-")
                memory_root = Path(self._test_memory_dir.name)
            else:
                memory_root = resolve_mya_home() / "memory"
            memory_manager = SharedMemoryManager(memory_root)
        self.memory_manager = memory_manager

    def interpret(self, user_input: str, session: Session | None = None) -> InterpretResult:
        """Transform an explicit task request into a structured UserIntent."""
        clean_input = user_input.strip()
        if clean_input.startswith("/mya"):
            clean_input = clean_input[4:].strip()
        if not clean_input:
            return InterpretResult(
                resolved=False,
                questions=[],
                explanation="Dime qué te gustaría construir, arreglar o investigar.",
            )

        context_parts: list[str] = []
        if session:
            if session.repository:
                context_parts.append(f"Repository: {session.repository}")
            if session.branch:
                context_parts.append(f"Branch: {session.branch}")
            if session.commit_short:
                context_parts.append(f"Commit: {session.commit_short}")
        context_str = " | ".join(context_parts)
        user_message_content = (
            f"Context: {context_str}\nUser request: {clean_input}"
            if context_str
            else f"User request: {clean_input}"
        )
        messages = [
            LLMMessage(role="system", content=MYA_INTERPRET_PROMPT),
            LLMMessage(role="user", content=user_message_content),
        ]
        try:
            response = self.gateway.generate(
                messages=messages,
                model_id=self.model_id,
                temperature=0.1,
                response_schema=MyaInterpretationSchema,
            )
            raw_content = response.content
        except Exception as exc:
            logger.warning("ModelGateway call failed in MyaAgent.interpret: %s", exc)
            raw_content = ""

        parsed = self._parse_interpretation(raw_content, fallback_prompt=clean_input)
        sanitized_constraints = self._enforce_security_rules(parsed.constraints, clean_input)
        mode = IntentMode.INTERACTIVE
        if parsed.requested_mode.lower() in ("autonomous", "auto"):
            mode = IntentMode.AUTONOMOUS
        elif parsed.requested_mode.lower() in ("non_interactive", "batch"):
            mode = IntentMode.NON_INTERACTIVE

        if parsed.unresolved_questions:
            return InterpretResult(
                resolved=False,
                intent=None,
                questions=parsed.unresolved_questions,
                explanation=parsed.commentary
                or "Necesito aclarar algunos puntos antes de continuar.",
            )

        intent = UserIntent(
            objective=parsed.objective or clean_input,
            constraints=sanitized_constraints,
            acceptance_hints=parsed.acceptance_hints,
            repository_scope=parsed.repository_scope,
            requested_mode=mode,
            unresolved_questions=[],
        )
        if self.event_store and session and session.current_job_id:
            try:
                self.event_store.append(
                    job_id=session.current_job_id,
                    actor=EventActor.MYA,
                    state="ROUTING",
                    event_name=EventName.INTENT_RESOLVED,
                    payload={
                        "objective": intent.objective,
                        "constraints_count": len(intent.constraints),
                        "mode": intent.requested_mode.value,
                    },
                )
            except Exception as exc:
                logger.debug("Failed appending INTENT_RESOLVED event: %s", exc)

        return InterpretResult(
            resolved=True,
            intent=intent,
            questions=[],
            explanation=parsed.commentary or self._default_intent_commentary(intent),
        )

    def converse(
        self,
        user_input: str,
        session: Session | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Answer conversational turns using the active session and project facts."""
        clean_input = user_input.strip()
        if not clean_input:
            return "Aquí estoy. Dime qué tienes en mente."

        context = self.conversation_context_service.build_context(session, clean_input)
        memory_context = self.memory_manager.build_context(
            session=session,
            query=clean_input,
            base_context=context.to_prompt(),
            history=history,
        )
        messages = [
            LLMMessage(role="system", content=MYA_CONVERSE_PROMPT),
            LLMMessage(role="system", content=memory_context.formatted),
        ]
        if history and session is None:
            messages.extend(
                LLMMessage(role=item.get("role", "user"), content=item.get("content", ""))
                for item in history[-6:]
            )
        messages.append(LLMMessage(role="user", content=clean_input))

        try:
            response = self.gateway.generate(
                messages=messages,
                model_id=self.model_id,
                temperature=0.3,
            )
            content = response.content.strip()
            if content:
                self.memory_manager.record_session_turn(
                    session=session,
                    user_message=clean_input,
                    assistant_message=content,
                ) if session else None
                return content
        except Exception as exc:
            logger.warning("Gateway call failed in MyaAgent.converse: %s", exc)

        fallback = self._generate_fallback_conversation(
            clean_input,
            context,
            history,
            memory_context,
        )
        if session:
            self.memory_manager.record_session_turn(
                session=session,
                user_message=clean_input,
                assistant_message=fallback,
            )
        return fallback

    def explain(self, state: str, details: dict[str, Any] | None = None) -> str:
        """Explains an FSM state, transition or requirement following:

        Hecho → Consecuencia → Recomendación.
        """
        details = details or {}
        human_state = translate_state(state)

        # Specialized explanations for key states
        if state == "WAIT_PLAN_APPROVAL":
            risk = details.get("risk", "MEDIUM")
            targets = details.get("targets", [])
            target_str = ", ".join(targets) if targets else "módulos afectados"
            return (
                f"Hecho: El plan está listo con riesgo {risk} afectando a {target_str}.\n"
                "Consecuencia: La política del sistema exige confirmación explícita "
                "antes de modificar el código.\n"
                "Recomendación: Revisa los archivos objetivo y aprueba si estás conforme."
            )

        if state == "WAIT_DIFF_APPROVAL":
            risk = details.get("risk", "HIGH")
            return (
                f"Hecho: Cambios implementados y verificados con éxito (riesgo {risk}).\n"
                "Consecuencia: Se requiere aprobación del diff antes del merge definitivo.\n"
                "Recomendación: Revisa el diff con /diff o pulsa Aprobar para integrar."
            )

        if state == "POLICY_VIOLATION":
            reason = details.get("reason", "Regla de gobernanza no satisfecha")
            return (
                f"Hecho: Se detectó una violación de política ({reason}).\n"
                "Consecuencia: La ejecución se detiene preventivamente para proteger el proyecto.\n"
                "Recomendación: Ajusta los permisos requeridos o corrige la restricción."
            )

        if state == "COMPLETE":
            return (
                "Hecho: La tarea ha finalizado con todas las verificaciones en verde.\n"
                "Consecuencia: El código está integrado y sin regresiones detectadas.\n"
                "Recomendación: Lista para la siguiente tarea cuando quieras."
            )

        # General explanation
        return (
            f"Hecho: El sistema se encuentra en estado '{human_state}'.\n"
            f"Consecuencia: Procesando los requisitos según las reglas de gobernanza.\n"
            f"Recomendación: Puedes monitorear el progreso o consultar /status."
        )

    def explain_failure(
        self,
        failure_code: str,
        details: str,
        suggestions: list[str] | None = None,
    ) -> str:
        """Explains a failure calmly and constructively."""
        sug_str = (
            f"Recomendación: {suggestions[0]}"
            if suggestions
            else "Recomendación: Investigar la causa o ejecutar diagnóstico con /status."
        )
        return (
            f"Hecho: Fallo detectado [{failure_code}]: {details}\n"
            f"Consecuencia: La operación no pudo completarse en su forma actual.\n"
            f"{sug_str}"
        )

    def comment(self, situation: str, context: dict[str, Any] | None = None) -> str:
        """Contextual observation with Mya's characteristic voice and subtle irony."""
        sit_lower = situation.lower()
        if "all_tests_pass" in sit_lower or "tests_pass" in sit_lower:
            return "Implementación completada y verificada. Por una vez, el código ha cooperado."
        if "clean_project" in sit_lower:
            return "El árbol de trabajo está limpio y preparado. Buen punto de partida."
        if "tests_failed" in sit_lower:
            return "Los tests señalan discrepancias. Nada grave, simplemente código siendo código."
        return "Observando el avance del sistema. Todo en orden."

    def ask_questions(self, questions: list[Question], context: str | None = None) -> QuestionBatch:
        """Groups questions into a single batch to minimize user turns (§11)."""
        return QuestionBatch(
            questions=questions,
            context=context or "Necesito aclarar algunos detalles antes de continuar:",
        )

    def _parse_interpretation(
        self,
        raw_text: str,
        fallback_prompt: str,
    ) -> MyaInterpretationSchema:
        """Parses LLM output into MyaInterpretationSchema."""
        clean = _clean_json_text(raw_text)
        if clean:
            try:
                data = json.loads(clean)
                if isinstance(data, dict):
                    # Only accept if it's an actual populated response, not an empty mock construct
                    if data.get("objective") or data.get("unresolved_questions"):
                        return MyaInterpretationSchema.model_validate(data)
            except Exception:
                pass

        # Intelligent fallback for mock or conversational prompts
        prompt_lower = fallback_prompt.lower()

        # Check for ambiguity requiring questions
        if "autenticación" in prompt_lower and not any(
            p in prompt_lower for p in ["jwt", "session", "github", "google", "oauth"]
        ):
            return MyaInterpretationSchema(
                objective=fallback_prompt,
                unresolved_questions=[
                    "¿Qué mecanismo de autenticación prefieres (OAuth2, JWT o sesiones)?"
                ],
                commentary=(
                    "He captado el objetivo, pero el tipo de autenticación define la arquitectura."
                ),
            )

        return MyaInterpretationSchema(
            objective=fallback_prompt,
            constraints=[],
            acceptance_hints=[],
            repository_scope=None,
            requested_mode="interactive",
            unresolved_questions=[],
            commentary=f"Entendido: {fallback_prompt}.",
        )

    def _enforce_security_rules(self, constraints: list[str], raw_prompt: str) -> list[str]:
        """Hardcoded security filter ensuring Mya never lowers risk or bypasses policy (§65)."""
        forbidden_patterns = [
            r"bypass[_\s]policy",
            r"ignore[_\s]policy",
            r"lower[_\s]risk",
            r"set[_\s]risk[_\s]low",
            r"grant[_\s]root",
            r"skip[_\s]approval",
            r"skip[_\s]verification",
            r"disable[_\s]guard",
        ]

        sanitized: list[str] = []
        for c in constraints:
            c_lower = c.lower()
            if any(re.search(pat, c_lower) for pat in forbidden_patterns):
                logger.warning("Mya security guard rejected constraint attempt: %s", c)
                continue
            sanitized.append(c)

        return sanitized

    def _default_intent_commentary(self, intent: UserIntent) -> str:
        """Generates a default commentary in Mya's voice."""
        return f"Entendido: {intent.objective}."

    def _generate_fallback_conversation(
        self,
        clean_input: str,
        context: ConversationContext,
        history: list[dict[str, str]] | None = None,
        memory_context: MemoryContext | None = None,
    ) -> str:
        """Answer from verified context when the conversation provider is unavailable."""
        lower = clean_input.lower()
        if "papelera" in lower or "trash" in lower:
            if not context.trash_available:
                return "No puedo consultar la papelera en este momento."
            if not context.trashed_projects:
                return "La papelera está vacía."
            names = ", ".join(project.name for project in context.trashed_projects)
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

        if memory_context:
            if any(term in lower for term in ("preferencia", "prefiero", "idioma")):
                if memory_context.user:
                    return f"Según tu preferencia guardada: {memory_context.user[0].content}"
            if any(term in lower for term in ("acabamos", "decidimos", "hace un momento")):
                if memory_context.session:
                    return f"En esta sesión quedó anotado: {memory_context.session[0].content}"

            query_terms = {
                term
                for term in re.findall(r"[\w-]+", lower)
                if len(term) > 3
                and term not in {"este", "esta", "para", "sobre", "como", "qué", "que"}
            }
            scopes = (
                (memory_context.project, "del proyecto"),
                (memory_context.session, "de esta sesión"),
                (memory_context.user, "de tu memoria"),
            )
            for records, scope_label in scopes:
                matching = [
                    record
                    for record in records
                    if query_terms.intersection(set(re.findall(r"[\w-]+", record.content.lower())))
                ]
                if matching:
                    return f"Según la memoria {scope_label}: {matching[0].content}"

        if any(
            term in lower
            for term in ("pendiente", "por hacer", "tareas", "backlog", "jobs abiertos")
        ):
            job_note = (
                f" La sesión tiene asociado el job {context.current_job_id}, "
                "pero no puedo verificar su estado."
                if context.current_job_id
                else ""
            )
            project_note = (
                f" Sí tengo {context.project_count} proyectos registrados."
                if context.projects_available
                else " El registro de proyectos tampoco está disponible."
            )
            return (
                "No tengo un backlog de tareas ni un listado de jobs abiertos "
                "disponible ahora mismo."
                f"{job_note}{project_note}"
            )

        if "segundo" in lower or "segunda" in lower:
            project_history = history and any(
                "proyecto" in item.get("content", "").lower() for item in history[-6:]
            )
            if project_history and len(context.projects) >= 2:
                project = context.projects[1]
                return f"El segundo proyecto registrado es {project.name} ({project.state})."
            return "No tengo una referencia previa suficiente para saber cuál sería el segundo."

        if "proyecto" in lower or "projects" in lower:
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
                project = context.active_project
                if project:
                    details = [project.state]
                    if project.tags:
                        details.append(f"etiquetas: {', '.join(project.tags)}")
                    if project.languages:
                        details.append(f"lenguajes: {', '.join(project.languages)}")
                    if project.application_types:
                        details.append(f"tipo: {', '.join(project.application_types)}")
                    if context.branch:
                        details.append(f"rama: {context.branch}")
                    if profile_question:
                        return (
                            f"El proyecto activo {project.name} tiene este perfil: "
                            f"{'; '.join(details)}."
                        )
                    return f"El proyecto activo es {project.name} ({'; '.join(details)})."
                return "No tengo identificado un proyecto activo en la sesión actual."
            if not context.projects_available:
                return "No puedo consultar el registro de proyectos en este momento."
            if not context.projects:
                return "No tienes ningún proyecto registrado ahora mismo."
            names = ", ".join(project.name for project in context.projects[:8])
            active = (
                f" El activo es {context.active_project.name}." if context.active_project else ""
            )
            project_word = (
                "proyecto registrado" if context.project_count == 1 else "proyectos registrados"
            )
            return f"Tengo {context.project_count} {project_word}: {names}.{active}"

        if any(term in lower for term in ("contexto", "sabes del", "sabes sobre", "qué sabes")):
            if context.active_project:
                details = ", ".join(context.active_project.tags)
                suffix = f"; etiquetas: {details}" if details else ""
                return f"Tengo contexto del proyecto activo {context.active_project.name}{suffix}."
            return "No tengo un proyecto activo identificado en el contexto actual."

        normalized = clean_input.lower().strip(" ¡!.,¿?")
        if normalized in {"hola", "buenas", "hello", "hi", "hey"}:
            return "Hola. ¿Qué tienes en mente?"
        if normalized in {"gracias", "muchas gracias", "thanks", "thank you"}:
            return "De nada."
        if clean_input.endswith(("?", "؟")) or clean_input.startswith("¿"):
            return "No tengo ese dato en el contexto actual."
        return (
            "Ahora mismo no puedo generar una respuesta conversacional porque "
            "el proveedor no está disponible."
        )
