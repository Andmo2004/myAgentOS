"""Append-only cryptographic event logging models according to §2, §24, §25."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventActor(StrEnum):
    """Actors permitted to emit events in the system (§24)."""

    JOB_CONTROLLER = "JOB_CONTROLLER"
    ROUTER = "ROUTER"
    PLANNER = "PLANNER"
    WORKER = "WORKER"
    TEST_AUTHOR = "TEST_AUTHOR"
    TOOL_BROKER = "TOOL_BROKER"
    POLICY_ENGINE = "POLICY_ENGINE"
    SANDBOX = "SANDBOX"
    VERIFICATION_GUARD = "VERIFICATION_GUARD"
    INDEPENDENT_REVIEWER = "INDEPENDENT_REVIEWER"
    MERGE_CONTROLLER = "MERGE_CONTROLLER"
    CURATOR = "CURATOR"
    CONTINUITY_ANALYST = "CONTINUITY_ANALYST"
    SKILL_REGISTRY = "SKILL_REGISTRY"
    USER = "USER"


class EventName(StrEnum):
    """Formal transition and lifecycle event names (§24)."""

    TASK_CREATED = "TASK_CREATED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    SKILL_ACTIVATED = "SKILL_ACTIVATED"
    DATA_CLASSIFIED = "DATA_CLASSIFIED"
    DATA_APPROVAL_REQUESTED = "DATA_APPROVAL_REQUESTED"
    DATA_APPROVAL_GRANTED = "DATA_APPROVAL_GRANTED"
    DATA_APPROVAL_DENIED = "DATA_APPROVAL_DENIED"
    PLAN_CONTEXT_BUILT = "PLAN_CONTEXT_BUILT"
    PLAN_GENERATED = "PLAN_GENERATED"
    RISK_ASSESSED = "RISK_ASSESSED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    WORKER_CONTEXT_BUILT = "WORKER_CONTEXT_BUILT"
    WORKTREE_READY = "WORKTREE_READY"
    TEST_AUTHORED = "TEST_AUTHORED"
    MODEL_CALL_STARTED = "MODEL_CALL_STARTED"
    MODEL_CALL_COMPLETED = "MODEL_CALL_COMPLETED"
    EGRESS_BLOCKED = "EGRESS_BLOCKED"
    BUDGET_RESERVED = "BUDGET_RESERVED"
    BUDGET_RECONCILED = "BUDGET_RECONCILED"
    BUDGET_PAUSED = "BUDGET_PAUSED"
    WORKER_STARTED = "WORKER_STARTED"
    TOOL_CALL = "TOOL_CALL"
    PATCH_CREATED = "PATCH_CREATED"
    POLICY_CHECKED = "POLICY_CHECKED"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    SANDBOX_STARTED = "SANDBOX_STARTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    TEST_FAILED = "TEST_FAILED"
    FAILURE_CLASSIFIED = "FAILURE_CLASSIFIED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CONTEXT_EXPANDED = "CONTEXT_EXPANDED"
    ENV_REPAIR_STARTED = "ENV_REPAIR_STARTED"
    REVIEW_COMPLETED = "REVIEW_COMPLETED"
    BASE_REBASED = "BASE_REBASED"
    STALE_PLAN = "STALE_PLAN"
    TIMEOUT = "TIMEOUT"
    ESCALATED = "ESCALATED"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    MERGE_COMPLETED = "MERGE_COMPLETED"
    KNOWLEDGE_UPDATE_STARTED = "KNOWLEDGE_UPDATE_STARTED"
    NOTE_PROPOSED = "NOTE_PROPOSED"

    # Project Continuation Audit events (§29)
    PROJECT_SNAPSHOT_CREATED = "PROJECT_SNAPSHOT_CREATED"
    STATIC_DISCOVERY_STARTED = "STATIC_DISCOVERY_STARTED"
    STATIC_DISCOVERY_COMPLETED = "STATIC_DISCOVERY_COMPLETED"
    DYNAMIC_DIAGNOSTICS_STARTED = "DYNAMIC_DIAGNOSTICS_STARTED"
    DYNAMIC_DIAGNOSTICS_COMPLETED = "DYNAMIC_DIAGNOSTICS_COMPLETED"
    FINDING_DETECTED = "FINDING_DETECTED"
    FINDING_CLASSIFIED = "FINDING_CLASSIFIED"
    CONTINUATION_SYNTHESIS_STARTED = "CONTINUATION_SYNTHESIS_STARTED"
    CONTINUATION_REPORT_CREATED = "CONTINUATION_REPORT_CREATED"
    CONTINUATION_CONTEXT_VALIDATED = "CONTINUATION_CONTEXT_VALIDATED"
    CONTINUATION_CONTEXT_STALE = "CONTINUATION_CONTEXT_STALE"
    NOTE_VALIDATED = "NOTE_VALIDATED"
    KNOWLEDGE_UPDATE_COMPLETED = "KNOWLEDGE_UPDATE_COMPLETED"
    JOB_FAILED = "JOB_FAILED"
    JOB_CANCELLED = "JOB_CANCELLED"
    JOB_COMPLETED = "JOB_COMPLETED"


GENESIS_HASH = "0" * 64


class Event(BaseModel):
    """Immutable audit trail event with cryptographic hash chaining (§24)."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = "2.1.0"
    actor: EventActor
    state: str
    event_name: EventName
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    event_hash: str

    @classmethod
    def calculate_hash(
        cls,
        event_id: str,
        job_id: str,
        timestamp: datetime,
        schema_version: str,
        actor: EventActor,
        state: str,
        event_name: EventName,
        payload: dict[str, Any],
        prev_hash: str,
    ) -> str:
        """Deterministic canonical hash calculation using SHA-256."""
        payload_canonical = json.dumps(payload, sort_keys=True, default=str)
        canonical_str = (
            f"{event_id}|{job_id}|{timestamp.isoformat()}|{schema_version}|"
            f"{actor.value}|{state}|{event_name.value}|{payload_canonical}|{prev_hash}"
        )
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    @classmethod
    def create(
        cls,
        job_id: str,
        actor: EventActor,
        state: str,
        event_name: EventName,
        payload: dict[str, Any] | None = None,
        prev_hash: str = GENESIS_HASH,
        event_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> "Event":
        """Factory method to construct an Event with its verified canonical SHA-256 hash."""
        e_id = event_id or str(uuid.uuid4())
        ts = timestamp or datetime.now(UTC)
        p = payload or {}
        computed_hash = cls.calculate_hash(
            event_id=e_id,
            job_id=job_id,
            timestamp=ts,
            schema_version="2.1.0",
            actor=actor,
            state=state,
            event_name=event_name,
            payload=p,
            prev_hash=prev_hash,
        )
        return cls(
            event_id=e_id,
            job_id=job_id,
            timestamp=ts,
            schema_version="2.1.0",
            actor=actor,
            state=state,
            event_name=event_name,
            payload=p,
            prev_hash=prev_hash,
            event_hash=computed_hash,
        )

    def verify_integrity(self, expected_prev_hash: str | None = None) -> bool:
        """Verifies both internal hash integrity and optionally prev_hash linkage."""
        if expected_prev_hash is not None and self.prev_hash != expected_prev_hash:
            return False
        expected_hash = self.calculate_hash(
            event_id=self.event_id,
            job_id=self.job_id,
            timestamp=self.timestamp,
            schema_version=self.schema_version,
            actor=self.actor,
            state=self.state,
            event_name=self.event_name,
            payload=self.payload,
            prev_hash=self.prev_hash,
        )
        return self.event_hash == expected_hash
