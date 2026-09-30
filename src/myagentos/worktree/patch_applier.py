"""PatchSet application and content hash verification according to §12."""

import hashlib
import subprocess
from pathlib import Path

from myagentos.core.models.patch import PatchOperation, PatchSet


def calculate_file_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hash of a file on disk."""
    if not file_path.exists():
        return ""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def apply_patch_set(
    worktree_path: Path,
    patch_set: PatchSet,
    verify_before_hash: bool = True,
) -> tuple[bool, str | None]:
    """Applies all patches in a PatchSet to the worktree and verifies integrity hashes (§12)."""
    for file_patch in patch_set.files:
        target = worktree_path / file_patch.path

        # 1. Verify before state
        if file_patch.operation in (PatchOperation.MODIFY, PatchOperation.DELETE):
            if not target.exists():
                op_val = file_patch.operation.value
                return False, f"File to {op_val} does not exist: {file_patch.path}"
            actual_before = calculate_file_sha256(target)
            if (
                verify_before_hash
                and file_patch.sha256_before
                and actual_before != file_patch.sha256_before
            ):
                return (
                    False,
                    f"Hash mismatch before applying patch to {file_patch.path}: "
                    f"expected {file_patch.sha256_before}, got {actual_before}",
                )

        # 2. Apply operation
        if file_patch.operation == PatchOperation.DELETE:
            target.unlink()

        elif file_patch.operation == PatchOperation.RENAME:
            if not file_patch.old_path:
                return False, f"Rename operation missing old_path for {file_patch.path}"
            old_target = worktree_path / file_patch.old_path
            if not old_target.exists():
                return False, f"Rename source does not exist: {file_patch.old_path}"
            target.parent.mkdir(parents=True, exist_ok=True)
            old_target.rename(target)
            if file_patch.patch:
                target.write_text(file_patch.patch, encoding="utf-8")

        elif file_patch.operation == PatchOperation.CREATE:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file_patch.patch, encoding="utf-8")

        elif file_patch.operation == PatchOperation.MODIFY:
            # Check if patch is unified diff or direct replacement content
            if file_patch.patch.startswith("---") or "\n@@" in file_patch.patch:
                # Apply using git apply
                res = subprocess.run(
                    ["git", "apply", "--whitespace=nowarn", "-"],
                    input=file_patch.patch,
                    cwd=str(worktree_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode != 0:
                    return (
                        False,
                        f"git apply failed for {file_patch.path}: {res.stderr.strip()}",
                    )
            else:
                target.write_text(file_patch.patch, encoding="utf-8")

        # 3. Verify after state
        if file_patch.operation in (
            PatchOperation.MODIFY,
            PatchOperation.CREATE,
            PatchOperation.RENAME,
        ):
            actual_after = calculate_file_sha256(target)
            if file_patch.sha256_after and actual_after != file_patch.sha256_after:
                return (
                    False,
                    f"Hash mismatch after applying patch to {file_patch.path}: "
                    f"expected {file_patch.sha256_after}, got {actual_after}",
                )

    return True, None
