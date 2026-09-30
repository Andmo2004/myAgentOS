from pathlib import Path

from myagentos.core.models.event import EventName
from myagentos.core.store.event_store import EventStore
from myagentos.mya.commands.handlers import CommandHandlerService
from myagentos.router.models import RoutingIntent


def test_handle_sci_mode(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    handler = CommandHandlerService(event_store=store)

    result = handler.handle_sci_mode(
        "¿Cómo comparar la latencia de dos arquitecturas?", job_id="sci-1"
    )
    assert "SCIENTIFIC ANALYSIS MODE" in result
    assert "Research Question" in result
    assert "Hypotheses & Assumptions" in result
    assert "Methodology" in result
    assert "Evidence & Data" in result
    assert "Limitations" in result
    assert "Conclusion" in result
    assert "no modifica el código" in result

    # Check event
    events = store.load_events("sci-1")
    assert any(e.event_name == EventName.MYA_COMMAND_RECEIVED for e in events)


def test_handle_deep_research_invariant(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    handler = CommandHandlerService(event_store=store)

    result = handler.handle_deep_research("Estrategias de caching distribuido", job_id="res-1")
    assert "DEEP RESEARCH REPORT" in result
    assert "Executive Summary" in result
    assert "Sources & Evidence" in result
    assert "Comparison & Trade-offs" in result
    assert "Conflicting Findings" in result
    assert "Open Questions" in result
    # Invariant: Does not modify code, asks for approval to convert to plan
    assert "no modifica el repositorio por defecto" in result
    assert "¿Quieres que convierta esta conclusión en un plan" in result

    events = store.load_events("res-1")
    event_names = [e.event_name for e in events]
    assert EventName.MYA_RESEARCH_STARTED in event_names
    assert EventName.MYA_RESEARCH_COMPLETED in event_names


def test_handle_optimize(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    handler = CommandHandlerService(event_store=store)

    result = handler.handle_optimize("Pipeline de eventos", job_id="opt-1")
    assert "OPTIMIZATION ANALYSIS" in result
    assert "Bottlenecks & Findings" in result
    assert "Observed bottleneck" in result
    assert "Optimization Candidates" in result
    assert "Expected Impact & Trade-offs" in result
    assert "Proposal" in result
    assert "El usuario decide si desea aplicar" in result


def test_handle_decision_maps_disagreements(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    handler = CommandHandlerService(event_store=store)

    result = handler.handle_decision("¿PostgreSQL o MongoDB?", job_id="dec-1")
    assert "DECISION PERSPECTIVES & CONSENSUS MAP" in result
    assert "Architect" in result
    assert "Performance" in result
    assert "Security" in result
    assert "Maintainability" in result
    assert "Cost" in result
    assert "Areas of Agreement" in result
    assert "Areas of Disagreement" in result
    assert "Recommended Decision Criteria" in result

    events = store.load_events("dec-1")
    event_names = [e.event_name for e in events]
    assert EventName.MYA_DECISION_STARTED in event_names
    assert EventName.MYA_DECISION_COMPLETED in event_names


def test_handle_security_and_cloud(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    handler = CommandHandlerService(event_store=store)

    sec_result = handler.handle_security("API de autenticación", job_id="sec-1")
    assert "CYBERSECURITY & OWASP AUDIT" in sec_result
    assert "Audit Findings" in sec_result
    assert "Policy Engine Integration" in sec_result

    cloud_result = handler.handle_cloud("Despliegue AWS", job_id="cld-1")
    assert "CLOUD INFRASTRUCTURE MODE" in cloud_result
    assert "Candidate Skills Activated" in cloud_result
    assert "Security Boundary Invariant" in cloud_result
    assert "Secret Broker" in cloud_result


def test_handle_fast_routing():
    handler = CommandHandlerService()

    # Low risk prompt -> DIRECT_WORKER_CODE
    dec_low, msg_low = handler.handle_fast("corrige un typo en el README")
    assert dec_low.intent == RoutingIntent.DIRECT_WORKER_CODE
    assert "Ruta rápida activada" in msg_low

    # High risk prompt -> Escalated to PLANNED_CODE
    dec_high, msg_high = handler.handle_fast("delete all data and drop production database")
    assert dec_high.intent == RoutingIntent.PLANNED_CODE
    assert "Re-escalado a flujo planificado" in msg_high
