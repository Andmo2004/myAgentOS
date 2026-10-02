"""Verification Guard and test harness protection exports."""

from myagentos.verification.guard import VerificationGuard, VerificationResult
from myagentos.verification.manifest import TestManifest
from myagentos.verification.profile import VerificationProfile
from myagentos.verification.protector import restore_protected_paths

__all__ = [
    "TestManifest",
    "VerificationGuard",
    "VerificationProfile",
    "VerificationResult",
    "restore_protected_paths",
]
