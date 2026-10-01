"""Session management for the interactive UI.

The session is NOT the source of truth for the project.
Authority remains in the Event Store, Job Store, and Project Knowledge.
The session is a local convenience for the UI process.
"""

import getpass
import hashlib
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from myagentos.categorization.models import ProjectProfile


def _local_user_id() -> str:
    username = getpass.getuser().strip().lower() or "local-user"
    return "local-" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:20]


def _active_session_id(project_key: str) -> str:
    """Resume this user's latest session for the same project across restarts."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return str(uuid.uuid4())[:8]
    from myagentos.config.paths import resolve_mya_home

    active_path = resolve_mya_home() / "memory" / "active_session.json"
    user_id = _local_user_id()
    hashed_project_key = hashlib.sha256(project_key.encode("utf-8")).hexdigest()
    try:
        if active_path.is_file():
            active = json.loads(active_path.read_text(encoding="utf-8"))
            if (
                active.get("user_id") == user_id
                and active.get("project_key_hash") == hashed_project_key
            ):
                return str(active["session_id"])
    except (OSError, ValueError, KeyError, TypeError):
        pass

    session_id = str(uuid.uuid4())[:8]
    try:
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text(
            json.dumps(
                {
                    "user_id": user_id,
                    "project_key_hash": hashed_project_key,
                    "session_id": session_id,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            active_path.parent.chmod(0o700)
            active_path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass
    return session_id


class GitInfo(BaseModel):
    """Git repository information detected from the working directory."""

    model_config = ConfigDict(frozen=True)

    repository: str
    branch: str
    commit: str
    commit_short: str
    clean: bool


class Session(BaseModel):
    """Local session state for the interactive UI."""

    model_config = ConfigDict(frozen=False)

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = Field(default_factory=_local_user_id)
    project_id: str = ""
    repository: str = ""
    branch: str = ""
    commit: str = ""
    commit_short: str = ""
    working_tree_clean: bool = True
    current_job_id: str | None = None
    active_mode: str = "interactive"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    repo_root: Path = Field(default_factory=lambda: Path.cwd())
    project_profile: ProjectProfile | None = None


def detect_git_info(path: Path | None = None) -> GitInfo | None:
    """Detect Git repository information from the given path.

    Returns None if not inside a Git repository.
    """
    cwd = str(path or Path.cwd())

    try:
        # Check if inside a git repo
        res = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return None

        # Get repo name from root directory
        root_res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        repo_name = Path(root_res.stdout.strip()).name if root_res.returncode == 0 else "unknown"

        # Get branch
        branch_res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "unknown"

        # Get commit hash
        commit_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        commit = commit_res.stdout.strip() if commit_res.returncode == 0 else "unknown"
        commit_short = commit[:7] if len(commit) >= 7 else commit

        # Check working tree status
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        clean = status_res.returncode == 0 and not status_res.stdout.strip()

        return GitInfo(
            repository=repo_name,
            branch=branch,
            commit=commit,
            commit_short=commit_short,
            clean=clean,
        )
    except FileNotFoundError:
        # git not installed
        return None


def create_session(repo_path: Path | None = None) -> Session:
    """Create a new session, auto-detecting Git info and cached profile if available."""
    root = (repo_path or Path.cwd()).resolve()
    git_info = detect_git_info(root)

    session = Session(
        user_id=_local_user_id(),
        session_id=_active_session_id(str(root)),
        repo_root=root,
    )

    if git_info:
        session.project_id = git_info.repository
        session.repository = git_info.repository
        session.branch = git_info.branch
        session.commit = git_info.commit
        session.commit_short = git_info.commit_short
        session.working_tree_clean = git_info.clean

    # Load cached project profile if available
    profile_path = root / ".myagentos" / "project_profile.json"
    if profile_path.is_file():
        try:
            session.project_profile = ProjectProfile.model_validate_json(
                profile_path.read_text(encoding="utf-8")
            )
        except Exception:
            pass

    return session
