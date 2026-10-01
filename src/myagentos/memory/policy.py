"""Deterministic write and retrieval policy for shared memory."""

from __future__ import annotations

import re

from myagentos.core.models.data_policy import DataClassification
from myagentos.memory.models import MemoryRecord


class MemoryPolicy:
    """Keep credentials out of memory and exclude restricted or stale records."""

    max_record_chars = 8_000
    _secret_patterns = (
        re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"ghp_[0-9a-zA-Z]{36}"),
        re.compile(r"AIza[0-9A-Za-z-_]{35}"),
        re.compile(r"sk-(?:live-|proj-)?[a-zA-Z0-9_-]{20,}"),
    )
    _credential_patterns = (
        re.compile(r"(?i)(api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+"),
        re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]{12,}"),
    )

    def validate_write(self, content: str, classification: str) -> None:
        if len(content) > self.max_record_chars:
            raise ValueError("Memory record exceeds the configured character limit")
        normalized_classification = classification.lower()
        if normalized_classification not in {
            DataClassification.PUBLIC.value,
            DataClassification.INTERNAL.value,
        }:
            raise ValueError("Only public or internal content may enter conversational memory")
        if any(pattern.search(content) for pattern in self._secret_patterns):
            raise ValueError("Memory content was rejected by the secret scanner")
        if any(pattern.search(content) for pattern in self._credential_patterns):
            raise ValueError("Memory content resembles a credential and was rejected")

    def is_retrievable(self, record: MemoryRecord) -> bool:
        if record.status not in {"active", "verified"}:
            return False
        if record.classification not in {
            DataClassification.PUBLIC.value,
            DataClassification.INTERNAL.value,
        }:
            return False
        if any(pattern.search(record.content) for pattern in self._secret_patterns):
            return False
        return not any(pattern.search(record.content) for pattern in self._credential_patterns)
