"""Deterministic Job Controller: sole authority over FSM transitions (§3, §8)."""

from typing import Any

from myagentos.core.models.event import Event, EventActor, EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore
from myagentos.core.store.state_projector import JobManifest, StateProjector
from myagentos.fsm.states import JobState
from myagentos.fsm.transitions import TransitionTable


class JobController:
    """Deterministic orchestrator managing FSM transitions, event logging, and state projection."""

    def __init__(self, job_id: str, event_store: EventStore) -> None:
        self.job_id = job_id
        self.event_store = event_store
        self.projector = StateProjector(event_store)

        # Initialize from existing events if any
        manifest = self.projector.project_manifest(job_id)
        self.current_state = JobState(manifest.current_state)
        self.risk_level = manifest.risk_level

    @classmethod
    def create(cls, job_id: str, event_store: EventStore) -> "JobController":
        return cls(job_id=job_id, event_store=event_store)

    def transition(
        self,
        event_name: EventName,
        actor: EventActor,
        payload: dict[str, Any] | None = None,
    ) -> tuple[JobState, Event]:
        """Validates guards, transitions to next state, and appends the immutable event."""
        payload = payload or {}
        next_state = TransitionTable.get_next_state(
            current_state=self.current_state,
            event_name=event_name,
            payload=payload,
        )

        # Update monotonic risk if present in event payload
        if "level" in payload and payload["level"] in RiskLevel.__members__:
            assessed_level = RiskLevel(payload["level"])
            if assessed_level > self.risk_level:
                self.risk_level = assessed_level

        # Append event to append-only log with cryptographic chaining
        event = self.event_store.append(
            job_id=self.job_id,
            actor=actor,
            state=next_state.value,
            event_name=event_name,
            payload=payload,
        )

        self.current_state = next_state
        self.projector.save_manifest(self.job_id)
        return next_state, event

    def get_manifest(self) -> JobManifest:
        return self.projector.project_manifest(self.job_id)

    def check_obsolescence(
        self,
        approved_base_commit: str,
        current_commit: str,
        changed_files_between_commits: list[str],
        plan_scope_files: set[str],
        protected_paths: list[str],
    ) -> bool:
        """Implements the single normative obsolescence rule (§8.4).

        Returns True if the plan is still valid (safe to rebase), or False if STALE_PLAN.
        """
        if approved_base_commit == current_commit:
            return True

        from fnmatch import fnmatch

        changed_set = set(changed_files_between_commits)

        # Check collision with approved plan scope
        if changed_set & plan_scope_files:
            return False

        # Check collision with protected paths
        for changed_file in changed_files_between_commits:
            for pattern in protected_paths:
                if fnmatch(changed_file, pattern):
                    return False

        return True
