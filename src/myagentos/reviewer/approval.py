"""Versioned Diff Approval bound to SHA-256 diff hashes according to §8.4 and §15.2."""

import hashlib

from myagentos.core.models.patch import PatchSet
from myagentos.core.models.review import DiffApproval
from myagentos.core.models.risk import RiskLevel


def compute_diff_hash(patch_set: PatchSet) -> str:
    """Computes an immutable SHA-256 digest over the unified diff (§8.4)."""
    diff_text = patch_set.to_unified_diff()
    return hashlib.sha256(diff_text.encode("utf-8")).hexdigest()


class DiffApprovalManager:
    """Governs diff approvals and prevents applying unapproved diff modifications (§15.2)."""

    def requires_diff_approval(
        self,
        risk_level: RiskLevel,
        require_medium: bool = False,
    ) -> bool:
        """Determines if the risk level mandates diff approval before merge (§5.3)."""
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return True
        if risk_level == RiskLevel.MEDIUM and require_medium:
            return True
        return False

    def create_approval(
        self,
        job_id: str,
        patch_set: PatchSet,
        approved: bool = True,
        approved_by: str = "user",
        version: int = 1,
        feedback: str | None = None,
    ) -> DiffApproval:
        """Creates an approval bound immutably to the current diff hash (§8.4)."""
        diff_h = compute_diff_hash(patch_set)
        return DiffApproval(
            job_id=job_id,
            diff_hash=diff_h,
            approved=approved,
            approved_by=approved_by,
            version=version,
            feedback=feedback,
        )

    def validate_approval(
        self,
        approval: DiffApproval | None,
        patch_set: PatchSet,
    ) -> tuple[bool, str | None]:
        """Validates that a recorded approval matches the exact current patch set diff hash."""
        if approval is None:
            return False, "No diff approval recorded for job"

        if not approval.approved:
            return False, f"Diff approval was explicitly rejected by {approval.approved_by}"

        current_hash = compute_diff_hash(patch_set)
        if approval.diff_hash != current_hash:
            return (
                False,
                f"Diff hash mismatch: approval bound to {approval.diff_hash[:12]}, "
                f"but current diff is {current_hash[:12]}. Prior approval invalidated (§8.4).",
            )

        return True, None
