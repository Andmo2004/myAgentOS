"""Merge Controller: serializes repository merges and atomic commits according to §16."""

import fcntl
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from myagentos.core.errors import MyAgentOSError


class MergeConflictError(MyAgentOSError):
    """Raised when an unresolvable merge conflict occurs (§8.2, §16)."""


class MergeController:
    """Manages serialized repository merges with mutual exclusion and simulated validation (§16)."""

    def __init__(self, repo_root: str | Path, lock_path: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.lock_path = (
            Path(lock_path).resolve() if lock_path else self.repo_root / ".myagentos" / "merge.lock"
        )

    @contextmanager
    def repository_lock(self) -> Generator[None, None, None]:
        """Acquires exclusive file lock for this repository to serialize merges (§16)."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(self.lock_path, "w", encoding="utf-8")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def commit_in_job_branch(
        self,
        worktree_path: Path,
        job_id: str,
        commit_message: str | None = None,
    ) -> str:
        """Stages changes and creates an atomic commit in branch agentic/<job_id>."""
        msg = commit_message or f"agentic({job_id}): apply verified patch set"

        # git add -A
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(worktree_path),
            capture_output=True,
            check=True,
        )

        # git commit -m <msg>
        commit_res = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_res.returncode != 0 and "nothing to commit" not in commit_res.stdout:
            raise MyAgentOSError(f"Commit failed in worktree: {commit_res.stderr}")

        # git rev-parse HEAD
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return rev.stdout.strip()

    def simulate_merge(self, base_commit: str, head_commit: str) -> tuple[bool, str | None]:
        """Simulates merge using git merge-tree to detect conflicts deterministically (§16)."""
        res = subprocess.run(
            ["git", "merge-tree", base_commit, head_commit],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return False, f"Merge simulation failed: {res.stderr}"

        # If merge-tree output contains conflict markers ("+<<<<<<<")
        if "+<<<<<<<" in res.stdout or "CONFLICT" in res.stdout:
            return False, "Merge conflict detected in simulation"

        return True, None
