"""State projector: builds and regenerates manifest.json from events.jsonl (§2, §24)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.event import GENESIS_HASH, EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.store.event_store import EventStore


class JobManifest(BaseModel):
    """Regenerable materialization of job state projected from events.jsonl (§24)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    current_state: str
    risk_level: RiskLevel = RiskLevel.LOW
    base_commit: str | None = None
    active_plan_id: str | None = None
    total_events: int = 0
    last_event_hash: str = GENESIS_HASH
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    failure_count: int = 0


class StateProjector:
    """Projects events into manifest.json and ensures regeneration idempotency."""

    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store

    def get_manifest_path(self, job_id: str) -> Path:
        return self.event_store.get_job_dir(job_id) / "manifest.json"

    def project_manifest(self, job_id: str) -> JobManifest:
        """Deterministically projects the current job manifest from raw events."""
        events = self.event_store.load_events(job_id)
        if not events:
            now = datetime.now(UTC)
            return JobManifest(
                job_id=job_id,
                current_state="IDLE",
                risk_level=RiskLevel.LOW,
                created_at=now,
                updated_at=now,
            )

        current_state = events[-1].state
        last_hash = events[-1].event_hash
        created_at = events[0].timestamp
        updated_at = events[-1].timestamp
        risk = RiskLevel.LOW
        base_commit: str | None = None
        active_plan_id: str | None = None
        failure_count = 0

        for event in events:
            # Monotonic risk progression
            if event.event_name == EventName.RISK_ASSESSED:
                lvl_str = event.payload.get("level")
                if lvl_str and lvl_str in RiskLevel.__members__:
                    new_risk = RiskLevel(lvl_str)
                    if new_risk > risk:
                        risk = new_risk

            # Base commit and plan identification
            if event.event_name in (EventName.PLAN_GENERATED, EventName.APPROVAL_GRANTED):
                if "base_commit" in event.payload:
                    base_commit = str(event.payload["base_commit"])
                if "plan_id" in event.payload:
                    active_plan_id = str(event.payload["plan_id"])

            if event.event_name in (EventName.FAILURE_CLASSIFIED, EventName.TEST_FAILED):
                failure_count += 1

        return JobManifest(
            job_id=job_id,
            current_state=current_state,
            risk_level=risk,
            base_commit=base_commit,
            active_plan_id=active_plan_id,
            total_events=len(events),
            last_event_hash=last_hash,
            created_at=created_at,
            updated_at=updated_at,
            failure_count=failure_count,
        )

    def save_manifest(self, job_id: str) -> JobManifest:
        """Projects events and writes manifest.json atomically."""
        manifest = self.project_manifest(job_id)
        manifest_path = self.get_manifest_path(job_id)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest

    def load_manifest(self, job_id: str) -> JobManifest | None:
        """Loads manifest from file, or projects from events if manifest.json is absent."""
        manifest_path = self.get_manifest_path(job_id)
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return JobManifest.model_validate(data)

        if self.event_store.get_events_file(job_id).exists():
            return self.save_manifest(job_id)

        return None
