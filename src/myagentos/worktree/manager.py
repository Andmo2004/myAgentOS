"""Ephemeral Git worktree management according to §11.7."""

import shutil
import subprocess
from pathlib import Path

from myagentos.core.errors import MyAgentOSError


class WorktreeError(MyAgentOSError):
    """Raised when git worktree operations fail."""


class WorktreeManager:
    """Manages ephemeral git worktrees isolated per job (§11.7)."""

    def __init__(self, repo_root: str | Path, worktrees_dir: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.worktrees_dir = (
            Path(worktrees_dir).resolve()
            if worktrees_dir
            else self.repo_root / ".myagentos" / "worktrees"
        )

    def get_worktree_path(self, job_id: str) -> Path:
        return self.worktrees_dir / job_id

    def get_branch_name(self, job_id: str) -> str:
        return f"agentic/{job_id}"

    def create_worktree(self, job_id: str, base_commit: str) -> Path:
        """Creates an ephemeral git worktree branched from base_commit."""
        worktree_path = self.get_worktree_path(job_id)
        branch_name = self.get_branch_name(job_id)

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)

        if worktree_path.exists():
            self.remove_worktree(job_id)

        # git worktree add -B <branch> <path> <base_commit>
        cmd = [
            "git",
            "worktree",
            "add",
            "-B",
            branch_name,
            str(worktree_path),
            base_commit,
        ]
        res = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise WorktreeError(f"Failed to create worktree for job {job_id}: {res.stderr}")

        return worktree_path

    def remove_worktree(self, job_id: str) -> None:
        """Removes an ephemeral worktree cleanly and prunes git records."""
        worktree_path = self.get_worktree_path(job_id)
        branch_name = self.get_branch_name(job_id)

        if worktree_path.exists():
            # git worktree remove --force <path>
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(self.repo_root),
                capture_output=True,
                check=False,
            )

        # Prune dead worktrees
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(self.repo_root),
            capture_output=True,
            check=False,
        )

        # Delete branch if exists
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            cwd=str(self.repo_root),
            capture_output=True,
            check=False,
        )

        # Ensure directory is removed
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

    def get_head_commit(self, repo_dir: Path | None = None) -> str:
        """Returns current HEAD commit hash of the repository (§8.4)."""
        target = repo_dir or self.repo_root
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return "local-head"
        return res.stdout.strip()

    def get_changed_files_between(
        self,
        commit_a: str,
        commit_b: str,
        repo_dir: Path | None = None,
    ) -> list[str]:
        """Returns the list of relative file paths changed between commit_a and commit_b (§8.4)."""
        target = repo_dir or self.repo_root
        res = subprocess.run(
            ["git", "diff", "--name-only", commit_a, commit_b],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return []
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]

    def rebase_branch(self, worktree_path: Path, new_base: str) -> bool:
        """Rebases the branch in worktree_path onto new_base commit (§8.4).

        Returns True if rebase succeeds, False if conflicts occur.
        """
        if not worktree_path.is_dir() or not (worktree_path / ".git").exists():
            return True

        # Check for uncommitted working tree modifications
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if status_res.returncode == 0 and status_res.stdout.strip():
            # Commit dirty files so git rebase can replay the commit
            subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), check=False)
            subprocess.run(
                ["git", "commit", "-m", "WIP: agentic changes before rebase"],
                cwd=str(worktree_path),
                capture_output=True,
                check=False,
            )

        rebase_res = subprocess.run(
            ["git", "rebase", new_base],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if rebase_res.returncode != 0:
            subprocess.run(
                ["git", "rebase", "--abort"],
                cwd=str(worktree_path),
                capture_output=True,
                check=False,
            )
            return False

        return True
