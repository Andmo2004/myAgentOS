"""Deterministic project snapshot capture according to §7 and §8.1."""

import hashlib
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from myagentos.continuity.models import ProjectSnapshot, WorkingTreeState

KNOWN_LOCKFILES = [
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
]


def _hash_file(path: Path) -> str:
    """Computes SHA-256 of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Runs a git command safely and returns (exit_code, stdout)."""
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode, res.stdout.strip()
    except Exception:
        return -1, ""


def create_project_snapshot(
    repo_root: str | Path,
    snapshot_id: str | None = None,
) -> ProjectSnapshot:
    """Captures an immutable deterministic ProjectSnapshot (§7)."""
    root = Path(repo_root).resolve()
    sid = snapshot_id or f"snap-{uuid.uuid4().hex[:8]}"

    # Check if git repository
    rc, git_root = _run_git(["rev-parse", "--show-toplevel"], root)
    is_git = rc == 0

    tracked_files: list[str] = []
    base_commit = "unversioned"
    branch = "unknown"
    git_remotes: dict[str, str] = {}
    submodules: list[str] = []

    uncommitted_files: list[str] = []
    modified_files: list[str] = []
    untracked_files: list[str] = []
    is_clean = True

    if is_git:
        _, base_commit = _run_git(["rev-parse", "HEAD"], root)
        _, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)

        # Tracked files
        _, ls_out = _run_git(["ls-files"], root)
        if ls_out:
            tracked_files = [line.strip() for line in ls_out.splitlines() if line.strip()]

        # Remotes
        _, remotes_out = _run_git(["remote", "-v"], root)
        for line in remotes_out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and "(fetch)" in line:
                git_remotes[parts[0]] = parts[1]

        # Submodules
        _, submod_out = _run_git(["submodule", "status"], root)
        for line in submod_out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                submodules.append(parts[1])

        # Working tree status
        _, status_out = _run_git(["status", "--porcelain"], root)
        if status_out:
            for line in status_out.splitlines():
                if len(line) >= 4:
                    status_code = line[:2]
                    file_path = line[3:].strip()
                    uncommitted_files.append(file_path)
                    if "?" in status_code:
                        untracked_files.append(file_path)
                    else:
                        modified_files.append(file_path)
            is_clean = len(uncommitted_files) == 0
    else:
        # Fallback: scan filesystem
        for p in root.rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
                tracked_files.append(str(p.relative_to(root)))

    # Compute working tree content hash
    wt_hasher = hashlib.sha256()
    wt_hasher.update(base_commit.encode("utf-8"))
    for f in sorted(uncommitted_files):
        wt_hasher.update(f.encode("utf-8"))
    working_tree_hash = wt_hasher.hexdigest()

    working_tree = WorkingTreeState(
        clean=is_clean,
        content_hash=working_tree_hash,
        uncommitted_files=uncommitted_files,
        modified_files=modified_files,
        untracked_files=untracked_files,
    )

    # Project size in bytes
    project_size_bytes = 0
    for rel_path in tracked_files:
        fpath = root / rel_path
        if fpath.is_file():
            try:
                project_size_bytes += fpath.stat().st_size
            except OSError:
                pass

    # Lockfiles
    lock_hashes: dict[str, str] = {}
    for lockname in KNOWN_LOCKFILES:
        lock_path = root / lockname
        if lock_path.is_file():
            try:
                lock_hashes[lockname] = _hash_file(lock_path)
            except OSError:
                pass

    # Toolchain fingerprint
    fingerprint: dict[str, str] = {
        "python": sys.version.split()[0],
    }
    if shutil.which("git"):
        _, git_v = _run_git(["--version"], root)
        if git_v:
            fingerprint["git"] = git_v
    if shutil.which("uv"):
        try:
            uv_res = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if uv_res.returncode == 0:
                fingerprint["uv"] = uv_res.stdout.strip()
        except Exception:
            pass

    return ProjectSnapshot(
        snapshot_id=sid,
        repository=root.name,
        base_commit=base_commit,
        branch=branch,
        working_tree=working_tree,
        submodules=submodules,
        git_remotes=git_remotes,
        project_size_bytes=project_size_bytes,
        tracked_files=tracked_files,
        ignored_files_count=0,
        toolchain_fingerprint=fingerprint,
        dependency_lock_hashes=lock_hashes,
        policy_version="1.0",
        created_at=datetime.now(UTC),
    )
