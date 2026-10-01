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
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway
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
        clean = clean[len("```") :].strip()
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
    """The conversational LLM interface for Agentic OS.

    Mya interprets. Job Controller governs. Policy Engine authorizes.
    Workers execute. Verification Guard verifies.
    """

    def __init__(
        self,
        gateway: ModelGateway,
        model_id: str = "mock-mya",
        event_store: EventStore | None = None,
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id
        self.event_store = event_store

    def interpret(self, user_input: str, session: Session | None = None) -> InterpretResult:
        """Transforms natural language input into a structured UserIntent.

        Returns either:
        - A resolved UserIntent ready for the Job Controller
        - A list of clarifying questions if material information is missing
        """
        clean_input = user_input.strip()
        if clean_input.startswith("/mya"):
            clean_input = clean_input[4:].strip()

        if not clean_input:
            return InterpretResult(
                resolved=False,
                questions=[],
                explanation="Dime qué te gustaría construir, arreglar o investigar.",
            )

        # Build prompt context
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

        # Call ModelGateway
        try:
            resp = self.gateway.generate(
                messages=messages,
                model_id=self.model_id,
                temperature=0.1,
                response_schema=MyaInterpretationSchema,
            )
            raw_content = resp.content
        except Exception as exc:
            logger.warning("ModelGateway call failed in MyaAgent.interpret: %s", exc)
            raw_content = ""

        # Parse structured interpretation
        parsed = self._parse_interpretation(raw_content, fallback_prompt=clean_input)

        # Apply Hardcoded Security Invariants
        sanitized_constraints = self._enforce_security_rules(parsed.constraints, clean_input)

        # Determine mode
        mode = IntentMode.INTERACTIVE
        if parsed.requested_mode.lower() in ("autonomous", "auto"):
            mode = IntentMode.AUTONOMOUS
        elif parsed.requested_mode.lower() in ("non_interactive", "batch"):
            mode = IntentMode.NON_INTERACTIVE

        # If unresolved questions exist
        if parsed.unresolved_questions:
            return InterpretResult(
                resolved=False,
                intent=None,
                questions=parsed.unresolved_questions,
                explanation=parsed.commentary
                or "Necesito aclarar algunos puntos antes de continuar.",
            )

        # Construct resolved UserIntent
        intent = UserIntent(
            objective=parsed.objective or clean_input,
            constraints=sanitized_constraints,
            acceptance_hints=parsed.acceptance_hints,
            repository_scope=parsed.repository_scope,
            requested_mode=mode,
            unresolved_questions=[],
        )

        # Log event if event store provided
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

        commentary = parsed.commentary or self._default_intent_commentary(intent)

        return InterpretResult(
            resolved=True,
            intent=intent,
            questions=[],
            explanation=commentary,
        )

    def converse(
        self,
        user_input: str,
        session: Session | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """General dialogue with Mya's voice and personality."""
        clean_input = user_input.strip()
        if not clean_input:
            return "Aquí estoy. Dime qué tienes en mente."

        lower_input = clean_input.lower()
        if "proyectos" in lower_input and any(
            phrase in lower_input
            for phrase in (
                "tenemos",
                "mis proyectos",
                "listar proyectos",
                "ver proyectos",
                "qué proyectos tengo",
                "que proyectos tengo",
                "cuáles son mis proyectos",
                "cuales son mis proyectos",
                "lista de proyectos",
            )
        ):
            return self._generate_fallback_conversation(clean_input, session)

        messages: list[LLMMessage] = [LLMMessage(role="system", content=MYA_CONVERSE_PROMPT)]

        context_parts: list[str] = []
        if session:
            if session.repository:
                context_parts.append(f"Repository: {session.repository}")
            if session.branch:
                context_parts.append(f"Branch: {session.branch}")
            if session.commit_short:
                context_parts.append(f"Commit: {session.commit_short}")
            if session.project_profile:
                profile = session.project_profile
                tags = ", ".join(t.label for t in profile.visible_tags)
                languages = ", ".join(profile.stack.languages)
                app_types = ", ".join(profile.architecture.application_type)
                if tags:
                    context_parts.append(f"Project tags: {tags}")
                if languages:
                    context_parts.append(f"Project languages: {languages}")
                if app_types:
                    context_parts.append(f"Project application type: {app_types}")
        if context_parts:
            messages.append(
                LLMMessage(
                    role="system",
                    content=(
                        "## Current session context\n"
                        "Use this as factual context for the conversation. "
                        "It is metadata about the active project, not a substitute for reading file contents.\n"
                        + "\n".join(context_parts)
                    ),
                )
            )

        if history:
            for item in history[-6:]:  # Keep recent context
                messages.append(
                    LLMMessage(
                        role=item.get("role", "user"),
                        content=item.get("content", ""),
                    )
                )

        messages.append(LLMMessage(role="user", content=clean_input))

        try:
            resp = self.gateway.generate(
                messages=messages,
                model_id=self.model_id,
                temperature=0.3,
            )
            content = resp.content.strip()
            if (
                content
                and content != "Mock LLM output"
                and "propose_patch" not in content
                and "Default mock" not in content
            ):
                return content
        except Exception as exc:
            logger.warning("Gateway call failed in MyaAgent.converse: %s", exc)

        # Fallback response in Mya's voice
        return self._generate_fallback_conversation(clean_input, session)

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
            return (
                "Implementación completada y verificada. Por una vez, el código ha cooperado."
            )
        if "clean_project" in sit_lower:
            return "El árbol de trabajo está limpio y preparado. Buen punto de partida."
        if "tests_failed" in sit_lower:
            return (
                "Los tests señalan discrepancias. Nada grave, simplemente código siendo código."
            )
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
        session: Session | None = None,
    ) -> str:
        """Deterministic conversational responses matching Mya's voice."""
        lower = clean_input.lower()

        if lower.strip(" ¡!.,¿?") in {
            "hola",
            "hola mya",
            "buenas",
            "hello",
            "hi",
            "hey",
        }:
            return "Hola. ¿Qué tienes en mente?"

        if any(q in lower for q in ["quién eres", "quien eres", "who are you", "qué eres"]):
            return (
                "Soy Mya, la voz de Agentic OS. "
                "Yo converso, interpreto, explico y comento con serenidad e ironía comedida. "
                "Los agentes especializados (Planner, Worker, Reviewer) hacen el trabajo duro "
                "bajo la supervisión del Job Controller."
            )

        if any(
            q in lower
            for q in [
                "tienes contexto",
                "tienes información sobre este proyecto",
                "tienes informacion sobre este proyecto",
                "tienes información sobre esta aplicación",
                "tienes informacion sobre esta aplicacion",
                "conoces este proyecto",
                "conoces esta aplicación",
                "conoces esta aplicacion",
                "sabes algo de este proyecto",
                "sabes algo sobre este proyecto",
            ]
        ):
            repo_name = f" ({session.repository})" if session and session.repository else ""
            if session and session.project_profile:
                profile = session.project_profile
                languages = ", ".join(profile.stack.languages) or "el stack detectado"
                return (
                    f"Sí. Tengo contexto del proyecto activo{repo_name}, al menos de su metadato de sesión "
                    f"y de su perfil detectado. En concreto, veo {languages}. "
                    "Para hablar de una parte concreta del código necesitaría tenerla en el contexto de trabajo."
                )
            if session and session.repository:
                return (
                    f"Sí. Tengo contexto de la sesión y del repositorio activo{repo_name}. "
                    "Puedo usar ese contexto para orientarme, aunque para afirmar detalles concretos del código "
                    "necesito que estén disponibles en el contexto de trabajo."
                )
            return (
                "Sí, puedo trabajar con el contexto que Agentic OS tenga disponible de esta sesión. "
                "Ahora mismo no tengo metadatos de un repositorio activo para concretarlo más."
            )

        if any(c in lower for c in ["cómo estás", "como estas", "how are you"]):
            return "En calma y con todos los subsistemas nominales. Dime en qué nos enfocamos."

        if any(h in lower for h in ["ayuda", "help", "qué puedes hacer"]):
            return (
                "Puedes describirme cualquier tarea en lenguaje natural ('añade autenticación', "
                "'arregla los tests', 'continúa este proyecto'). "
                "Yo me encargo de sintetizar tu intención y coordinar con el sistema operativo."
            )

        project_queries = [
            "qué tipo de proyecto",
            "que tipo de proyecto",
            "qué es este proyecto",
            "que es este proyecto",
            "de qué trata este proyecto",
            "de que trata este proyecto",
            "cuéntame de este proyecto",
            "cuentame de este proyecto",
            "qué tecnologías",
            "que tecnologias",
            "cuál es el stack",
            "cual es el stack",
            "categoriza este proyecto",
            "qué tags",
            "que tags",
        ]
        if any(pq in lower for pq in project_queries):
            profile = session.project_profile if session else None
            if not profile and session and session.repo_root:
                from myagentos.categorization import ProjectCategorizationService

                try:
                    profile = ProjectCategorizationService().scan_project(session.repo_root)
                    session.project_profile = profile
                except Exception:
                    pass

            if profile:
                tags = " ".join(f"[{t.label}]" for t in profile.visible_tags)
                langs = ", ".join(profile.stack.languages) or "N/A"
                apps = ", ".join(profile.architecture.application_type) or "N/A"
                return (
                    f"Este proyecto ({profile.repository}) está categorizado como {tags}. "
                    f"Su stack principal incluye {langs}, estructurado principalmente como {apps}. "
                    "Todo auditado y listo para cualquier tarea que necesites planificar."
                )
            return (
                "Aún no he categorizado este proyecto en profundidad. "
                "Puedes usar el comando /categorize para generar el perfil completo "
                "y los tags visibles."
            )

        list_projects_queries = [
            "mis proyectos",
            "listar proyectos",
            "ver proyectos",
            "muéstrame mis proyectos",
            "muestrame mis proyectos",
            "qué proyectos tengo",
            "que proyectos tengo",
            "qué proyectos tenemos",
            "que proyectos tenemos",
            "qué proyectos tenemos en mente",
            "que proyectos tenemos en mente",
            "cuáles son mis proyectos",
            "cuales son mis proyectos",
            "lista de proyectos",
        ]
        if any(lp in lower for lp in list_projects_queries) or (
            "proyectos" in lower and "tenemos" in lower
        ):
            from myagentos.projects.service import ProjectManagerService

            try:
                mgr = ProjectManagerService()
                projs = mgr.list_projects()
                if not projs:
                    return (
                        "No tienes ningún proyecto registrado en Agentic OS todavía. "
                        "Puedes crear uno nuevo con `myagentos project new <nombre>` "
                        "o registrar uno existente con /projects o `myagentos project add <path>`."
                    )
                lines = [f"Tienes {len(projs)} proyecto(s) activo(s) en Agentic OS:\n"]
                for p in projs:
                    tags = " ".join(f"[{t.label}]" for t in p.visible_tags)
                    lines.append(f"• {p.name} {tags} ({p.path})")
                lines.append("\nPuedes explorar o cambiar de proyecto con /projects.")
                return "\n".join(lines)
            except Exception as exc:
                return f"No he podido consultar los proyectos: {exc}"

        trash_queries = [
            "papelera",
            "proyectos en la papelera",
            "qué hay en la papelera",
            "que hay en la papelera",
        ]
        if any(tq in lower for tq in trash_queries):
            from myagentos.projects.service import ProjectManagerService

            try:
                mgr = ProjectManagerService()
                trash = mgr.list_trash()
                if not trash:
                    return "La papelera está vacía. Todos tus proyectos registrados están activos."
                lines = [f"Hay {len(trash)} proyecto(s) en la papelera:\n"]
                for p in trash:
                    lines.append(f"• {p.name} ({p.path})")
                lines.append(
                    "\nPuedes restaurarlos con /projects o "
                    "`myagentos project trash restore <nombre>`."
                )
                lines.append("Nota de seguridad: Sus repositorios en disco permanecen intactos.")
                return "\n".join(lines)
            except Exception as exc:
                return f"No he podido consultar la papelera: {exc}"

        delete_queries = [
            "borra este proyecto",
            "borrar este proyecto",
            "elimina este proyecto",
            "eliminar este proyecto",
            "borra el proyecto",
            "elimina el proyecto",
            "mover a la papelera",
        ]
        if any(dq in lower for dq in delete_queries):
            return (
                "Para proteger tu trabajo, yo no ejecuto eliminaciones de proyectos directamente. "
                "Puedes gestionar el ciclo de vida del proyecto desde el Project Explorer con "
                "/projects o usando `myagentos project trash move <nombre>`. "
                "Recuerda que mover a la papelera es reversible y que tus archivos en disco "
                "nunca se borran."
            )

        return "Sí, te sigo. Cuéntame un poco más y lo vemos juntos."
