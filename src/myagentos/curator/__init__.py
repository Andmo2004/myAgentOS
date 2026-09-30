"""Curator package managing post-merge knowledge extraction and staging according to §22."""

from myagentos.curator.agent import CuratorAgent
from myagentos.curator.staging import (
    MAX_NOTE_SIZE_BYTES,
    MAX_NOTES_PER_JOB,
    NoteStagingManager,
    StagingLimitExceeded,
    StagingLimitExceededError,
    StagingOverwriteViolation,
    StagingOverwriteViolationError,
)
from myagentos.curator.staleness import StalenessTracker
from myagentos.curator.validator import ANCHOR_PATTERN, DeterministicNoteValidator

__all__ = [
    "CuratorAgent",
    "NoteStagingManager",
    "DeterministicNoteValidator",
    "StalenessTracker",
    "MAX_NOTES_PER_JOB",
    "MAX_NOTE_SIZE_BYTES",
    "ANCHOR_PATTERN",
    "StagingLimitExceeded",
    "StagingLimitExceededError",
    "StagingOverwriteViolation",
    "StagingOverwriteViolationError",
]
