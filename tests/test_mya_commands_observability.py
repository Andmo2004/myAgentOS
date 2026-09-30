from pathlib import Path

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.store.event_store import EventStore
from myagentos.mya.commands.models import (
    ObservedFileState,
)
from myagentos.mya.commands.observability import ObservabilityService
from myagentos.ui.session import create_session


def test_observability_empty_job(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    svc = ObservabilityService(event_store=store)

    info_str = svc.render_info()
    assert "SESSION INFORMATION" in info_str
    assert "Budget remaining" in info_str

    telemetry_str = svc.render_telemetry()
    assert "AGENT TELEMETRY" in telemetry_str
    assert "Architect" in telemetry_str
    assert "Builder" in telemetry_str

    monitor_str = svc.render_monitor()
    assert "AGENTIC OS · LIVE MONITOR" in monitor_str
    assert "Architect" in monitor_str


def test_observability_with_job_events(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    job_id = "job-456"

    # Append model calls for Planner and Worker
    store.append(
        job_id=job_id,
        actor=EventActor.PLANNER,
        state="PLANNING",
        event_name=EventName.MODEL_CALL_COMPLETED,
        payload={"prompt_tokens": 4000, "completion_tokens": 1200, "cost_usd": 0.04},
    )
    store.append(
        job_id=job_id,
        actor=EventActor.WORKER,
        state="WORKING",
        event_name=EventName.MODEL_CALL_COMPLETED,
        payload={"prompt_tokens": 8000, "completion_tokens": 3000, "cost_usd": 0.12},
    )
    # Append files in context and proposed
    store.append(
        job_id=job_id,
        actor=EventActor.WORKER,
        state="WORKING",
        event_name=EventName.WORKER_CONTEXT_BUILT,
        payload={"context_files": ["src/service.py"]},
    )
    store.append(
        job_id=job_id,
        actor=EventActor.PLANNER,
        state="PLANNING",
        event_name=EventName.PLAN_GENERATED,
        payload={"target_files": ["tests/test_service.py"]},
    )

    svc = ObservabilityService(event_store=store)
    breakdown = svc.get_token_breakdown(job_id)
    assert breakdown["Planner"]["calls"] == 1
    assert breakdown["Planner"]["input"] == 4000
    assert breakdown["Planner"]["output"] == 1200

    assert breakdown["Worker"]["calls"] == 1
    assert breakdown["Worker"]["input"] == 8000
    assert breakdown["Worker"]["output"] == 3000

    activities = svc.get_agent_activities(job_id)
    builder = next(a for a in activities if a.agent_id == "worker_1")
    assert "src/service.py" in builder.files
    assert builder.files["src/service.py"] == ObservedFileState.READ
    assert builder.files["tests/test_service.py"] == ObservedFileState.PROPOSED

    # Render monitor
    session = create_session(tmp_path)
    session.current_job_id = job_id
    monitor_out = svc.render_monitor(job_id=job_id, session=session)
    assert "src/service.py" in monitor_out
    assert "READ" in monitor_out
    assert "PROPOSED" in monitor_out
