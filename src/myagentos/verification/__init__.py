"""Verification Guard and test harness protection exports."""

from myagentos.verification.guard import VerificationGuard, VerificationResult
from myagentos.verification.manifest import TestManifest
from myagentos.verification.protector import restore_protected_paths

__all__ = [
    "VerificationGuard",
    "VerificationResult",
    "TestManifest",
    "restore_protected_paths",
]
