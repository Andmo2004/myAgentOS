"""Maps raw EventStore events and semantic states into UI View Models (§9).

The UI is a derived projection of the Event Store (§4.1).
No business logic or authority is contained within the mapper.
"""

from collections.abc import Sequence
from typing import Any

from myagentos.core.models.event import Event, EventName
from myagentos.ui.theme.symbols import (
    FileActivityState,
    VisualStatus,
    get_status_symbol,
)
from myagentos.ui.visual.motion import MotionController, MotionMode
from myagentos.ui.visual.state import (
    AgentViewModel,
    FileActivityViewModel,
    JobViewModel,
    MyaViewModel,
    VerificationCheck,
    VerificationViewModel,
    VisualState,
)


class VisualStateMapper:
    """Projects system events and statuses into presentation view models."""

    def __init__(self, motion_controller: MotionController | None = None) -> None:
        self.motion = motion_controller or MotionController.get_instance()

    def map_status_to_visual(
        self,
        status: VisualStatus | str,
        ascii_only: bool = False,
        motion_mode: MotionMode | None = None,
    ) -> VisualState:
        """Converts a status enum to its visual counterpart with animations (§9)."""
        mode = motion_mode or self.motion.mode
        if isinstance(status, str):
            try:
                status = VisualStatus(status.lower())
            except ValueError:
                status = VisualStatus.IDLE

        symbol = get_status_symbol(status, ascii_only=ascii_only)

        # Operational animation rules (§4.2, §8)
        if status == VisualStatus.RUNNING:
            anim = "spinner" if mode == MotionMode.FULL else "none"
            emphasis = "active"
        elif status == VisualStatus.APPROVAL:
            anim = "pulse" if mode == MotionMode.FULL else "none"
            emphasis = "warning"
        elif status == VisualStatus.FAILED:
            anim = "none"
            emphasis = "error"
        elif status == VisualStatus.SUCCESS:
            anim = "none"
            emphasis = "active"
        elif status == VisualStatus.WAITING:
            anim = "none"
            emphasis = "dim"
        else:
            anim = "none"
            emphasis = "normal"

        return VisualState(
            status=status,
            symbol=symbol,
            emphasis=emphasis,
            animation=anim,
            label=status.value,
        )

    def map_job_events(self, events: Sequence[Event], job_id: str) -> JobViewModel:
        """Projects job events into JobViewModel."""
        status = VisualStatus.IDLE
        cost = 0.0
        risk = "LOW"
        title = ""

        for ev in events:
            if ev.job_id != job_id:
                continue

            name = ev.event_name
            if name == EventName.TASK_CREATED:
                status = VisualStatus.RUNNING
                title = str(ev.payload.get("task", ""))
            elif name == EventName.APPROVAL_REQUESTED:
                status = VisualStatus.APPROVAL
            elif name == EventName.APPROVAL_GRANTED:
                status = VisualStatus.RUNNING
            elif name == EventName.RISK_ASSESSED:
                risk = str(ev.payload.get("risk_level", "LOW"))
            elif name == EventName.MERGE_COMPLETED:
                status = VisualStatus.SUCCESS
            elif name in (
                EventName.APPROVAL_REJECTED,
                EventName.JOB_FAILED,
                EventName.TEST_FAILED,
            ):
                status = VisualStatus.FAILED
            elif name == EventName.MODEL_CALL_COMPLETED:
                cost += float(ev.payload.get("cost_usd", 0.0))

        return JobViewModel(
            job_id=job_id,
            title=title or f"Job {job_id}",
            status=status,
            cost_usd=cost,
            risk=risk,
        )

    def map_agent_events(
        self,
        events: Sequence[Event],
        agent_id: str,
        role: str,
        display_name: str,
    ) -> AgentViewModel:
        """Projects agent events into AgentViewModel."""
        status = VisualStatus.IDLE
        activity = "idle"
        in_tok = 0
        out_tok = 0
        cost = 0.0
        files: set[str] = set()

        for ev in events:
            if ev.actor.value != role.upper() and ev.payload.get("worker_id") != agent_id:
                continue

            status = VisualStatus.RUNNING
            if "task" in ev.payload:
                activity = str(ev.payload["task"])
            elif "target" in ev.payload:
                activity = str(ev.payload["target"])

            if "input_tokens" in ev.payload:
                in_tok += int(ev.payload["input_tokens"])
            if "output_tokens" in ev.payload:
                out_tok += int(ev.payload["output_tokens"])
            if "cost_usd" in ev.payload:
                cost += float(ev.payload["cost_usd"])
            if "file" in ev.payload:
                files.add(str(ev.payload["file"]))
            if "path" in ev.payload:
                files.add(str(ev.payload["path"]))

        return AgentViewModel(
            agent_id=agent_id,
            role=role,
            display_name=display_name,
            status=status,
            current_activity=activity,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            files=sorted(files),
        )

    def map_file_activities(self, events: Sequence[Event]) -> list[FileActivityViewModel]:
        """Categorizes files strictly into READ, TOUCHED, MODIFIED, PROPOSED, VERIFIED (§11)."""
        file_map: dict[str, FileActivityViewModel] = {}

        for ev in events:
            payload = ev.payload
            fpath = payload.get("file") or payload.get("path") or payload.get("target")
            if not fpath or not isinstance(fpath, str):
                continue

            state_str = str(payload.get("file_state", "")).upper()
            actor = ev.actor.value

            if state_str == "VERIFIED":
                state = FileActivityState.VERIFIED
            elif state_str == "PROPOSED":
                state = FileActivityState.PROPOSED
            elif (
                state_str == "MODIFIED"
                or "write" in str(payload.get("action", "")).lower()
                or "modify" in str(payload.get("action", "")).lower()
            ):
                state = FileActivityState.MODIFIED
            elif state_str == "TOUCHED" or "touch" in str(payload.get("action", "")).lower():
                state = FileActivityState.TOUCHED
            elif ev.event_name == EventName.PATCH_CREATED:
                state = FileActivityState.PROPOSED
            else:
                state = FileActivityState.READ

            file_map[fpath] = FileActivityViewModel(
                file_path=fpath,
                state=state,
                agent_id=actor,
            )

        return sorted(file_map.values(), key=lambda f: f.file_path)

    def map_verification_events(self, events: Sequence[Event]) -> VerificationViewModel:
        """Projects verification check results (§6.5)."""
        checks: dict[str, VerificationCheck] = {
            "test_suite": VerificationCheck(
                name="test_suite",
                label="test suite",
                status=VisualStatus.WAITING,
            ),
            "lint": VerificationCheck(
                name="lint",
                label="lint",
                status=VisualStatus.WAITING,
            ),
            "type_checks": VerificationCheck(
                name="type_checks",
                label="type checks",
                status=VisualStatus.WAITING,
            ),
            "protected_tests": VerificationCheck(
                name="protected_tests",
                label="protected tests",
                status=VisualStatus.WAITING,
            ),
            "policy_checks": VerificationCheck(
                name="policy_checks",
                label="policy checks",
                status=VisualStatus.WAITING,
            ),
        }
        overall = VisualStatus.IDLE

        for ev in events:
            if ev.event_name == EventName.VERIFICATION_COMPLETED:
                passed = ev.payload.get("passed", True)
                overall = VisualStatus.SUCCESS if passed else VisualStatus.FAILED
                for k in checks:
                    checks[k] = checks[k].model_copy(
                        update={"status": overall}
                    )
            elif ev.event_name == EventName.TEST_FAILED:
                overall = VisualStatus.FAILED
                checks["test_suite"] = checks["test_suite"].model_copy(
                    update={"status": VisualStatus.FAILED}
                )

        return VerificationViewModel(
            overall_status=overall,
            checks=list(checks.values()),
        )

    def map_mya_state(
        self,
        semantic_state: str = "IDLE",
        expression: str = "calm",
        activity: str = "idle",
        speech_bubble: str = "",
        avatar_mode: str = "dot",
        metadata: dict[str, Any] | None = None,
    ) -> MyaViewModel:
        """Constructs presentation-only MyaViewModel (§14, §15)."""
        return MyaViewModel(
            semantic_state=semantic_state,
            expression=expression,
            activity=activity,
            speech_bubble=speech_bubble,
            avatar_mode=avatar_mode,
            metadata=metadata or {},
        )
