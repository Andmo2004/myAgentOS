"""Tests for VisualStateMapper and Event-to-ViewModel projections (§9, §10)."""

from myagentos.core.models.event import GENESIS_HASH, Event, EventActor, EventName
from myagentos.ui.theme.symbols import FileActivityState, VisualStatus
from myagentos.ui.visual.mapper import VisualStateMapper
from myagentos.ui.visual.motion import MotionController, MotionMode


def test_map_status_to_visual_with_motion_modes() -> None:
    ctrl = MotionController(mode=MotionMode.FULL)
    mapper = VisualStateMapper(motion_controller=ctrl)

    # RUNNING in full motion has spinner
    vs_running = mapper.map_status_to_visual(VisualStatus.RUNNING)
    assert vs_running.symbol == "●"
    assert vs_running.animation == "spinner"
    assert vs_running.emphasis == "active"

    # RUNNING in reduced motion has no spinner
    ctrl.set_mode(MotionMode.REDUCED)
    vs_reduced = mapper.map_status_to_visual(VisualStatus.RUNNING)
    assert vs_reduced.animation == "none"

    # ASCII fallback
    vs_ascii = mapper.map_status_to_visual(VisualStatus.RUNNING, ascii_only=True)
    assert vs_ascii.symbol == "(*)"


def test_map_job_and_agent_events() -> None:
    mapper = VisualStateMapper()

    e1 = Event.create(
        job_id="job-100",
        actor=EventActor.ROUTER,
        state="INIT",
        event_name=EventName.TASK_CREATED,
        payload={"task": "Optimize queries"},
        prev_hash=GENESIS_HASH,
    )
    e2 = Event.create(
        job_id="job-100",
        actor=EventActor.WORKER,
        state="RUNNING",
        event_name=EventName.MODEL_CALL_COMPLETED,
        payload={
            "worker_id": "worker-01",
            "task": "Rewriting SQL query",
            "input_tokens": 1500,
            "output_tokens": 500,
            "cost_usd": 0.025,
            "file": "src/db/repo.py",
        },
        prev_hash=e1.event_hash,
    )

    events = [e1, e2]

    # Map job
    job_vm = mapper.map_job_events(events, "job-100")
    assert job_vm.job_id == "job-100"
    assert job_vm.title == "Optimize queries"
    assert job_vm.cost_usd == 0.025

    # Map agent
    agent_vm = mapper.map_agent_events(events, "worker-01", "Worker", "Worker 01")
    assert agent_vm.agent_id == "worker-01"
    assert agent_vm.role == "Worker"
    assert agent_vm.input_tokens == 1500
    assert agent_vm.output_tokens == 500
    assert "src/db/repo.py" in agent_vm.files


def test_map_file_activities_lifecycle() -> None:
    mapper = VisualStateMapper()

    e1 = Event.create(
        job_id="j1",
        actor=EventActor.WORKER,
        state="WORK",
        event_name=EventName.TOOL_CALL,
        payload={"file": "src/models.py", "action": "read"},
        prev_hash=GENESIS_HASH,
    )
    e2 = Event.create(
        job_id="j1",
        actor=EventActor.WORKER,
        state="WORK",
        event_name=EventName.PATCH_CREATED,
        payload={"file": "src/repo.py", "action": "write"},
        prev_hash=e1.event_hash,
    )
    e3 = Event.create(
        job_id="j1",
        actor=EventActor.TEST_AUTHOR,
        state="VERIFY",
        event_name=EventName.VERIFICATION_COMPLETED,
        payload={"file": "tests/test_repo.py", "file_state": "VERIFIED"},
        prev_hash=e2.event_hash,
    )

    files = mapper.map_file_activities([e1, e2, e3])
    file_dict = {f.file_path: f.state for f in files}

    assert file_dict["src/models.py"] == FileActivityState.READ
    assert file_dict["src/repo.py"] == FileActivityState.MODIFIED
    assert file_dict["tests/test_repo.py"] == FileActivityState.VERIFIED
