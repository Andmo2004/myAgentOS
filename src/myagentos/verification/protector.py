"""Restoration of protected test harness and paths from base_commit according to §13.3."""

import subprocess
from fnmatch import fnmatch
from pathlib import Path

from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS


def restore_protected_paths(
    worktree_path: Path,
    base_commit: str,
    protected_paths: list[str] | None = None,
) -> list[str]:
    """Force-checks out all protected paths from base_commit to guarantee harness integrity (§13.3).

    Returns list of paths that were checked out/restored.
    """
    active_protected = protected_paths or DEFAULT_PROTECTED_PATHS
    restored: list[str] = []

    # Get list of files modified or added in worktree relative to base_commit
    res = subprocess.run(
        ["git", "diff", "--name-only", base_commit],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        return restored

    modified_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]

    for modified in modified_files:
        is_protected = any(
            fnmatch(modified, pattern) or fnmatch(modified.strip("/"), pattern)
            for pattern in active_protected
        )
        if is_protected:
            # Force restore from base_commit
            subprocess.run(
                ["git", "checkout", base_commit, "--", modified],
                cwd=str(worktree_path),
                capture_output=True,
                check=False,
            )
            restored.append(modified)

    return restored
