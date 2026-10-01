"""Provider-independent memory records and bounded context models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

MemoryScope = Literal["user", "project", "session"]


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    scope: MemoryScope
    user_id: str | None
    project_id: str | None
    session_id: str | None
    namespace_id: str
    content: str
    status: str
    classification: str
    trust: str
    created_at: datetime
    updated_at: datetime
    source: str
    content_hash: str
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryLimits:
    max_records: dict[MemoryScope, int] = field(
        default_factory=lambda: {"user": 4, "project": 8, "session": 12}
    )
    max_chars: int = 12_000
    max_tokens_estimate: int = 3_000


@dataclass(frozen=True)
class MemoryContext:
    user: tuple[MemoryRecord, ...]
    project: tuple[MemoryRecord, ...]
    session: tuple[MemoryRecord, ...]
    formatted: str
    total_tokens_estimate: int
    memory_revision: str

    @property
    def records(self) -> tuple[MemoryRecord, ...]:
        return self.session + self.project + self.user
