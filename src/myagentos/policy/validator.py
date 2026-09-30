"""PatchSet validation and policy compliance according to §12 and §13."""

from fnmatch import fnmatch
from pathlib import PurePath

from myagentos.core.models.patch import PatchSet
from myagentos.core.models.token import CapabilityToken
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS


def validate_patch_set(
    patch_set: PatchSet,
    token: CapabilityToken,
    protected_paths: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Validates that a PatchSet satisfies capability token and security invariants (§12)."""
    violations: list[str] = []
    active_protected = protected_paths or DEFAULT_PROTECTED_PATHS

    # 1. Base commit validation
    if patch_set.base_commit != token.base_commit:
        violations.append(
            f"Base commit mismatch: patch has {patch_set.base_commit}, "
            f"token is bound to {token.base_commit}"
        )

    # 2. File and line limits
    if patch_set.total_files > token.limits.max_files:
        violations.append(
            f"File count limit exceeded: patch touches {patch_set.total_files} files "
            f"(max allowed: {token.limits.max_files})"
        )

    if patch_set.total_diff_lines > token.limits.max_diff_lines:
        violations.append(
            f"Diff line limit exceeded: patch has {patch_set.total_diff_lines} lines "
            f"(max allowed: {token.limits.max_diff_lines})"
        )

    # 3. Mode changes
    if patch_set.has_mode_changes:
        violations.append("Unauthorized file mode changes detected in patch")

    # 4. Path traversal, write scope, and protected paths per file
    for file_patch in patch_set.files:
        for path_to_check in [file_patch.path, file_patch.old_path]:
            if not path_to_check:
                continue

            # Path traversal detection
            pure = PurePath(path_to_check)
            if pure.is_absolute() or ".." in pure.parts:
                violations.append(f"Illegal path traversal detected in path: {path_to_check}")

            # Protected paths check (§13.2) -> Absolute zero tolerance
            for pattern in active_protected:
                if fnmatch(path_to_check, pattern) or fnmatch(path_to_check.strip("/"), pattern):
                    violations.append(
                        f"Patch attempts to modify protected path {path_to_check} "
                        f"(matches {pattern})"
                    )

            # Write scope check (§23)
            if not token.is_write_allowed(path_to_check):
                violations.append(
                    f"Path {path_to_check} is outside authorized write scope: {token.write_scope}"
                )

    return (len(violations) == 0, violations)
