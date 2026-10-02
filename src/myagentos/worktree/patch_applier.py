"""PatchSet application and verification according to §12 and AGF-001/006."""

import hashlib
import subprocess
from pathlib import Path

from myagentos.core.models.patch import PatchOperation, PatchSet
from myagentos.core.paths import (
    safe_delete_file,
    safe_rename_file,
    safe_write_text,
    validate_safe_path,
)


def calculate_file_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hash of a file on disk."""
    if not file_path.exists():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _extract_diff_headers(diff_text: str) -> list[str]:
    """Extracts target paths mentioned in unified diff headers."""
    targets: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            parts = line.split(maxsplit=1)
            if len(parts) > 1:
                target = parts[1].split("\t")[0].strip()
                if target.startswith("a/") or target.startswith("b/"):
                    target = target[2:]
                if target and target not in ("/dev/null", "dev/null"):
                    targets.append(target)
    return targets


def apply_patch_set(
    worktree_path: Path,
    patch_set: PatchSet,
    verify_before_hash: bool = True,
) -> tuple[bool, str | None]:
    """Applies patches in PatchSet transactionally, verifying containment and hashes (§12)."""
    resolved_wt = Path(worktree_path).resolve()

    # Step 1: Pre-validation of ALL files before applying ANY modifications
    seen_destinations: set[str] = set()
    for file_patch in patch_set.files:
        clean_path = file_patch.path.strip("/")
        if clean_path in seen_destinations:
            return False, f"Duplicate destination path in patch set: '{file_patch.path}'"
        seen_destinations.add(clean_path)

        # Defense-in-depth path containment (AGF-001, AGF-003)
        try:
            target = validate_safe_path(resolved_wt, file_patch.path, allow_symlinks=False)
        except Exception as e:
            return False, f"Path containment violation for '{file_patch.path}': {e}"

        # Operation-specific pre-validation
        if file_patch.operation == PatchOperation.CREATE:
            if target.exists():
                return False, f"Cannot CREATE existing file: '{file_patch.path}'"

        elif file_patch.operation in (PatchOperation.MODIFY, PatchOperation.DELETE):
            if not target.exists():
                return (
                    False,
                    f"File to {file_patch.operation.value} does not exist: '{file_patch.path}'",
                )
            if verify_before_hash and file_patch.sha256_before:
                actual_before = calculate_file_sha256(target)
                if actual_before != file_patch.sha256_before:
                    return (
                        False,
                        f"Hash mismatch before applying patch to {file_patch.path}: "
                        f"expected {file_patch.sha256_before}, got {actual_before}",
                    )

        elif file_patch.operation == PatchOperation.RENAME:
            if not file_patch.old_path:
                return False, f"Rename operation missing old_path for '{file_patch.path}'"
            try:
                old_target = validate_safe_path(
                    resolved_wt, file_patch.old_path, allow_symlinks=False, must_exist=True
                )
            except Exception as e:
                return False, f"Invalid rename source '{file_patch.old_path}': {e}"
            if not old_target.exists():
                return False, f"Rename source does not exist: '{file_patch.old_path}'"
            if target.exists():
                return False, f"Cannot rename to existing file: '{file_patch.path}'"

        # Diff header security analysis (AGF-001)
        if file_patch.patch.startswith("---") or "\n@@" in file_patch.patch:
            headers = _extract_diff_headers(file_patch.patch)
            for h in headers:
                clean_h = h.strip("/")
                clean_target = file_patch.path.strip("/")
                clean_old = file_patch.old_path.strip("/") if file_patch.old_path else None
                if clean_h != clean_target and clean_h != clean_old:
                    return (
                        False,
                        f"Diff for '{file_patch.path}' has header targeting '{h}' (AGF-001)",
                    )
                try:
                    validate_safe_path(resolved_wt, h, allow_symlinks=False)
                except Exception as e:
                    return False, f"Diff header path '{h}' is invalid: {e}"

    # Step 2: Journaling / Backups for Transactional Rollback (AGF-006)
    backups: dict[str, bytes] = {}
    created_paths: list[str] = []
    renamed_records: list[tuple[str, str]] = []

    for file_patch in patch_set.files:
        if file_patch.operation in (PatchOperation.MODIFY, PatchOperation.DELETE):
            target = resolved_wt / file_patch.path
            if target.exists():
                backups[file_patch.path] = target.read_bytes()
        elif file_patch.operation == PatchOperation.RENAME and file_patch.old_path:
            old_target = resolved_wt / file_patch.old_path
            if old_target.exists():
                backups[file_patch.old_path] = old_target.read_bytes()

    def _rollback() -> tuple[bool, str | None]:
        """Rolls back all changes made during this patch application."""
        rollback_errors = []
        # 1. Unlink newly created files
        for cpath in created_paths:
            try:
                target = resolved_wt / cpath
                if target.exists():
                    target.unlink()
            except Exception as ex:
                rollback_errors.append(f"Failed to remove created file '{cpath}': {ex}")

        # 2. Reverse renames
        for old_p, new_p in reversed(renamed_records):
            try:
                old_t = resolved_wt / old_p
                new_t = resolved_wt / new_p
                if new_t.exists() and not old_t.exists():
                    new_t.rename(old_t)
            except Exception as ex:
                rollback_errors.append(f"Failed to reverse rename '{new_p}' -> '{old_p}': {ex}")

        # 3. Restore backups
        for path_key, content_bytes in backups.items():
            try:
                b_target = resolved_wt / path_key
                b_target.parent.mkdir(parents=True, exist_ok=True)
                b_target.write_bytes(content_bytes)
            except Exception as ex:
                rollback_errors.append(f"Failed to restore backup of '{path_key}': {ex}")

        if rollback_errors:
            return False, "; ".join(rollback_errors)
        return True, None

    # Step 3: Transactional Execution
    try:
        for file_patch in patch_set.files:
            target = resolved_wt / file_patch.path

            if file_patch.operation == PatchOperation.DELETE:
                safe_delete_file(resolved_wt, file_patch.path)

            elif file_patch.operation == PatchOperation.RENAME:
                assert file_patch.old_path is not None
                safe_rename_file(resolved_wt, file_patch.old_path, file_patch.path)
                renamed_records.append((file_patch.old_path, file_patch.path))
                if file_patch.patch:
                    safe_write_text(resolved_wt, file_patch.path, file_patch.patch, overwrite=True)

            elif file_patch.operation == PatchOperation.CREATE:
                safe_write_text(resolved_wt, file_patch.path, file_patch.patch, overwrite=True)
                created_paths.append(file_patch.path)

            elif file_patch.operation == PatchOperation.MODIFY:
                if file_patch.patch.startswith("---") or "\n@@" in file_patch.patch:
                    # Apply using git apply
                    res = subprocess.run(
                        ["git", "apply", "--whitespace=nowarn", "-"],
                        input=file_patch.patch,
                        cwd=str(resolved_wt),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if res.returncode != 0:
                        raise RuntimeError(
                            f"git apply failed for {file_patch.path}: {res.stderr.strip()}"
                        )
                else:
                    safe_write_text(resolved_wt, file_patch.path, file_patch.patch, overwrite=True)

            # Step 4: Verify post-state hashes
            if file_patch.operation in (
                PatchOperation.MODIFY,
                PatchOperation.CREATE,
                PatchOperation.RENAME,
            ):
                actual_after = calculate_file_sha256(target)
                if file_patch.sha256_after and actual_after != file_patch.sha256_after:
                    raise RuntimeError(
                        f"Hash mismatch after applying patch to {file_patch.path}: "
                        f"expected {file_patch.sha256_after}, got {actual_after}"
                    )

        return True, None

    except Exception as app_err:
        rb_ok, rb_err = _rollback()
        if rb_ok:
            return False, f"Patch application failed and was rolled back cleanly: {app_err}"
        return (
            False,
            f"CRITICAL: Patch application failed and rollback failed ({rb_err}). "
            f"Original error: {app_err}",
        )
