"""Versioned Diff Approval bound to canonical patch digests (§8.4, §15.2, AGF-007)."""

import hashlib
import json

from myagentos.core.models.patch import PatchSet
from myagentos.core.models.review import DiffApproval
from myagentos.core.models.risk import RiskLevel


def compute_canonical_patch_digest(patch_set: PatchSet, schema_version: int = 2) -> str:
    """Computes an immutable canonical SHA-256 digest over the semantic patch set (AGF-007).

    Guarantees:
    - MODIFY to empty vs DELETE produce distinct digests.
    - Preserves file order and encodes operations, paths, renames, modes, and hashes.
    - Rejects duplicate destination paths.
    - Versioned schema for safe migration.
    """
    seen_destinations: set[str] = set()
    files_payload = []

    for f in patch_set.files:
        clean_path = f.path.strip("/")
        if clean_path in seen_destinations:
            raise ValueError(f"Duplicate destination path in patch set: '{f.path}'")
        seen_destinations.add(clean_path)

        patch_bytes_digest = hashlib.sha256(f.patch.encode("utf-8")).hexdigest()
        file_entry = {
            "path": clean_path,
            "operation": f.operation.value,
            "old_path": f.old_path.strip("/") if f.old_path else None,
            "mode_before": f.mode_before,
            "mode_after": f.mode_after,
            "sha256_before": f.sha256_before,
            "sha256_after": f.sha256_after,
            "patch_digest": patch_bytes_digest,
        }
        files_payload.append(file_entry)

    canonical_data = {
        "schema_version": schema_version,
        "job_id": patch_set.job_id,
        "base_commit": patch_set.base_commit,
        "files": files_payload,
    }

    serialized = json.dumps(canonical_data, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"v{schema_version}:{digest}"


def compute_diff_hash(patch_set: PatchSet) -> str:
    """Computes a canonical SHA-256 digest over the PatchSet (§8.4, AGF-007)."""
    return compute_canonical_patch_digest(patch_set, schema_version=2)


class DiffApprovalManager:
    """Governs diff approvals and prevents unapproved diff modifications (§15.2, AGF-007)."""

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
        schema_version: int = 2,
    ) -> DiffApproval:
        """Creates an approval bound immutably to the canonical patch digest (§8.4, AGF-007)."""
        diff_h = compute_canonical_patch_digest(patch_set, schema_version=schema_version)
        return DiffApproval(
            job_id=job_id,
            diff_hash=diff_h,
            approved=approved,
            approved_by=approved_by,
            version=version,
            feedback=feedback,
            schema_version=schema_version,
        )

    def validate_approval(
        self,
        approval: DiffApproval | None,
        patch_set: PatchSet,
    ) -> tuple[bool, str | None]:
        """Validates recorded approval matches the exact current patch set canonical digest."""
        if approval is None:
            return False, "No diff approval recorded for job"

        # AGF-007: Obsolete schema versions require renewal
        if getattr(approval, "schema_version", 1) < 2:
            return (
                False,
                "Approval uses obsolete schema version (< 2); renewal required (AGF-007).",
            )

        if not approval.approved:
            return False, f"Diff approval was explicitly rejected by {approval.approved_by}"

        try:
            current_hash = compute_canonical_patch_digest(
                patch_set, schema_version=approval.schema_version
            )
        except ValueError as err:
            return False, f"Invalid patch set structure: {err}"

        if approval.diff_hash != current_hash:
            return (
                False,
                f"Diff hash mismatch: approval bound to {approval.diff_hash[:16]}, "
                f"but current diff is {current_hash[:16]}. Prior approval invalidated (§8.4).",
            )

        return True, None
