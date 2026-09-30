"""Append-only cryptographic event store according to §2, §24."""

import json
from pathlib import Path
from typing import Any

from myagentos.core.errors import HashChainCorruptionError
from myagentos.core.models.event import GENESIS_HASH, Event, EventActor, EventName


class EventStore:
    """Manages append-only JSONL event logs with cryptographic hash verification per job."""

    def __init__(self, root_dir: str | Path = ".myagentos/jobs") -> None:
        self.root_dir = Path(root_dir)

    def get_job_dir(self, job_id: str) -> Path:
        return self.root_dir / job_id

    def get_events_file(self, job_id: str) -> Path:
        return self.get_job_dir(job_id) / "events.jsonl"

    def get_last_event(self, job_id: str) -> Event | None:
        events_file = self.get_events_file(job_id)
        if not events_file.exists():
            return None

        last_line: str | None = None
        with open(events_file, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped

        if last_line is None:
            return None

        data = json.loads(last_line)
        return Event.model_validate(data)

    def append(
        self,
        job_id: str,
        actor: EventActor,
        state: str,
        event_name: EventName,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        """Atomically appends a new event linked to the previous event's hash."""
        job_dir = self.get_job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        events_file = self.get_events_file(job_id)

        last_event = self.get_last_event(job_id)
        prev_hash = last_event.event_hash if last_event is not None else GENESIS_HASH

        event = Event.create(
            job_id=job_id,
            actor=actor,
            state=state,
            event_name=event_name,
            payload=payload or {},
            prev_hash=prev_hash,
        )

        with open(events_file, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

        return event

    def load_events(self, job_id: str) -> list[Event]:
        """Loads all events for a given job in sequential order."""
        events_file = self.get_events_file(job_id)
        if not events_file.exists():
            return []

        events: list[Event] = []
        with open(events_file, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    events.append(Event.model_validate_json(stripped))
        return events

    def verify_integrity(self, job_id: str) -> tuple[bool, str | None]:
        """Verifies the complete hash chain from GENESIS to the latest event.

        Returns (True, None) if intact, or (False, reason) if corrupted.
        """
        events = self.load_events(job_id)
        if not events:
            return True, None

        expected_prev = GENESIS_HASH
        for idx, event in enumerate(events):
            if event.prev_hash != expected_prev:
                return (
                    False,
                    f"Chain broken at index {idx}: expected prev_hash {expected_prev}, "
                    f"got {event.prev_hash}",
                )
            if not event.verify_integrity(expected_prev_hash=expected_prev):
                return (
                    False,
                    f"Event integrity check failed at index {idx} (event_id={event.event_id})",
                )
            expected_prev = event.event_hash

        return True, None

    def assert_integrity(self, job_id: str) -> None:
        """Raises HashChainCorruptionError if the event log was tampered with."""
        is_valid, reason = self.verify_integrity(job_id)
        if not is_valid:
            msg = f"Event store integrity failure for job {job_id}: {reason}"
            raise HashChainCorruptionError(msg)
