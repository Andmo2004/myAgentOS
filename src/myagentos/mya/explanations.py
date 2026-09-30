"""State and event translations for human-readable UX.

These are a presentation layer. They are NOT new FSM states.
The FSM states remain in fsm/states.py and are never modified here.
"""

from myagentos.core.models.event import EventName

# §38 — FSM state → human-readable UX label
STATE_TRANSLATIONS: dict[str, str] = {
    "IDLE": "Lista",
    "ROUTING": "Entendiendo solicitud",
    "DOC_LOOKUP_RUN": "Consultando documentación",
    "RESEARCH_RUN": "Investigando",
    "PROJECT_SNAPSHOT": "Capturando estado del proyecto",
    "STATIC_DISCOVERY": "Analizando proyecto",
    "DYNAMIC_DIAGNOSTICS": "Ejecutando diagnósticos",
    "FINDING_CLASSIFICATION": "Clasificando hallazgos",
    "CONTINUATION_SYNTHESIS": "Generando contexto",
    "CONTINUATION_REPORT_READY": "Análisis completado",
    "DATA_CLASSIFY": "Revisando datos",
    "WAIT_DATA_APPROVAL": "Esperando aprobación de datos",
    "PLAN_CONTEXT": "Analizando proyecto",
    "PLAN_SPEC": "Preparando plan",
    "RISK_FINAL": "Evaluando riesgo",
    "WAIT_PLAN_APPROVAL": "Esperando aprobación",
    "WORKER_CONTEXT": "Preparando contexto",
    "WORKTREE_READY": "Entorno preparado",
    "TEST_AUTHORING": "Escribiendo tests",
    "EXECUTE": "Implementando",
    "POLICY_VALIDATION": "Validando cambios",
    "VERIFY": "Ejecutando verificación",
    "FAILURE_CLASSIFY": "Analizando fallo",
    "INDEPENDENT_REVIEW": "Revisando cambios",
    "WAIT_DIFF_APPROVAL": "Esperando aprobación del diff",
    "MERGE_CHECK": "Preparando integración",
    "MERGE": "Integrando",
    "KNOWLEDGE_UPDATE": "Actualizando conocimiento",
    "COMPLETE": "Completado",
    "CANCELLED": "Cancelado",
    "TIMEOUT": "Tiempo agotado",
    "STALE_PLAN": "Plan obsoleto",
    "MERGE_CONFLICT": "Conflicto de merge",
    "POLICY_VIOLATION": "Violación de política",
    "BUDGET_PAUSED": "Presupuesto pausado",
    "ESCALATED": "Requiere intervención",
}

# Event name → short human message for streaming progress
EVENT_MESSAGES: dict[str, str] = {
    EventName.TASK_CREATED: "Tarea creada",
    EventName.ROUTE_SELECTED: "Ruta seleccionada",
    EventName.DATA_CLASSIFIED: "Datos clasificados",
    EventName.PLAN_CONTEXT_BUILT: "Contexto de planificación listo",
    EventName.PLAN_GENERATED: "Plan preparado",
    EventName.RISK_ASSESSED: "Riesgo evaluado",
    EventName.APPROVAL_GRANTED: "Aprobación concedida",
    EventName.APPROVAL_REJECTED: "Aprobación rechazada",
    EventName.WORKER_CONTEXT_BUILT: "Contexto de ejecución listo",
    EventName.WORKTREE_READY: "Entorno de trabajo preparado",
    EventName.PATCH_CREATED: "Cambios generados",
    EventName.POLICY_CHECKED: "Política validada",
    EventName.POLICY_VIOLATION: "Violación de política detectada",
    EventName.VERIFICATION_COMPLETED: "Verificación completada",
    EventName.TEST_FAILED: "Tests fallando",
    EventName.REVIEW_COMPLETED: "Revisión completada",
    EventName.MERGE_COMPLETED: "Integración completada",
    EventName.KNOWLEDGE_UPDATE_COMPLETED: "Conocimiento actualizado",
    EventName.JOB_FAILED: "Tarea fallida",
    EventName.JOB_COMPLETED: "Tarea completada",
}


def translate_state(state: str) -> str:
    """Translate an FSM state to a human-readable label."""
    return STATE_TRANSLATIONS.get(state, state)


def translate_event(event_name: str) -> str:
    """Translate an event name to a short human message."""
    return EVENT_MESSAGES.get(event_name, event_name)
