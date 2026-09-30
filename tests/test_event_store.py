"""Unit tests for EventStore and StateProjector."""

import json
from pathlib import Path

import pytest

from myagentos.core.errors import HashChainCorruptionError
from myagentos.core.models.event import GENESIS_HASH, EventActor, EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store import EventStore, StateProjector


def test_event_store_append_and_load(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    job_id = "job-test-1"

    e1 = store.append(
        job_id=job_id,
        actor=EventActor.JOB_CONTROLLER,
        state="IDLE",
        event_name=EventName.TASK_CREATED,
        payload={"query": "Implement payment validation"},
    )
    assert e1.prev_hash == GENESIS_HASH

    e2 = store.append(
        job_id=job_id,
        actor=EventActor.ROUTER,
        state="ROUTING",
        event_name=EventName.ROUTE_SELECTED,
        payload={"intent": "PLANNED_CODE"},
    )
    assert e2.prev_hash == e1.event_hash

    events = store.load_events(job_id)
    assert len(events) == 2
    assert events[0].event_id == e1.event_id
    assert events[1].event_id == e2.event_id

    # Integrity verification succeeds
    is_valid, reason = store.verify_integrity(job_id)
    assert is_valid
    assert reason is None
    store.assert_integrity(job_id)


def test_event_store_tamper_detection(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    job_id = "job-tamper"

    store.append(
        job_id=job_id,
        actor=EventActor.JOB_CONTROLLER,
        state="IDLE",
        event_name=EventName.TASK_CREATED,
    )
    store.append(
        job_id=job_id,
        actor=EventActor.ROUTER,
        state="ROUTING",
        event_name=EventName.ROUTE_SELECTED,
    )

    # Tamper with the first line directly on disk
    events_file = store.get_events_file(job_id)
    lines = events_file.read_text(encoding="utf-8").splitlines()
    data = json.loads(lines[0])
    data["payload"] = {"malicious_injection": "admin_granted"}
    lines[0] = json.dumps(data)
    events_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Integrity check should detect corruption
    is_valid, reason = store.verify_integrity(job_id)
    assert not is_valid
    assert reason is not None

    with pytest.raises(HashChainCorruptionError):
        store.assert_integrity(job_id)


def test_state_projector_manifest_reconstruction(tmp_path: Path) -> None:
    store = EventStore(root_dir=tmp_path)
    projector = StateProjector(store)
    job_id = "job-project-1"

    store.append(
        job_id=job_id,
        actor=EventActor.JOB_CONTROLLER,
        state="IDLE",
        event_name=EventName.TASK_CREATED,
    )
    store.append(
        job_id=job_id,
        actor=EventActor.POLICY_ENGINE,
        state="RISK_FINAL",
        event_name=EventName.RISK_ASSESSED,
        payload={"level": "HIGH"},
    )
    store.append(
        job_id=job_id,
        actor=EventActor.PLANNER,
        state="PLAN_SPEC",
        event_name=EventName.PLAN_GENERATED,
        payload={"plan_id": "plan-v1", "base_commit": "commit-12345"},
    )
    store.append(
        job_id=job_id,
        actor=EventActor.VERIFICATION_GUARD,
        state="VERIFY",
        event_name=EventName.TEST_FAILED,
        payload={"failure": "AssertionError in tests/test_payment.py"},
    )

    manifest = projector.project_manifest(job_id)
    assert manifest.job_id == job_id
    assert manifest.current_state == "VERIFY"
    assert manifest.risk_level == RiskLevel.HIGH
    assert manifest.base_commit == "commit-12345"
    assert manifest.active_plan_id == "plan-v1"
    assert manifest.total_events == 4
    assert manifest.failure_count == 1

    # Save and reload
    saved_manifest = projector.save_manifest(job_id)
    loaded_manifest = projector.load_manifest(job_id)
    assert loaded_manifest is not None
    assert loaded_manifest.last_event_hash == saved_manifest.last_event_hash
