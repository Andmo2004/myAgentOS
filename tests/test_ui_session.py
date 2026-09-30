"""Tests for UI session management and Git detection."""

from pathlib import Path

from myagentos.ui.session import Session, create_session, detect_git_info


class TestDetectGitInfo:
    """Tests for Git repository detection."""

    def test_detect_in_real_repo(self) -> None:
        """Should detect Git info in the current project repo."""
        repo_root = Path(__file__).parent.parent
        info = detect_git_info(repo_root)
        assert info is not None
        assert info.repository == "myAgentOS"
        assert len(info.commit) == 40  # full SHA
        assert len(info.commit_short) == 7
        assert isinstance(info.clean, bool)

    def test_detect_outside_repo(self, tmp_path: Path) -> None:
        """Should return None for a non-git directory."""
        info = detect_git_info(tmp_path)
        assert info is None


class TestCreateSession:
    """Tests for session creation."""

    def test_create_session_in_repo(self) -> None:
        """Should auto-detect project info from the repo."""
        repo_root = Path(__file__).parent.parent
        session = create_session(repo_root)
        assert session.repository == "myAgentOS"
        assert session.branch != ""
        assert session.commit_short != ""
        assert len(session.session_id) == 8

    def test_create_session_outside_repo(self, tmp_path: Path) -> None:
        """Should create a session with empty Git info."""
        session = create_session(tmp_path)
        assert session.repository == ""
        assert session.branch == ""

    def test_session_is_mutable(self) -> None:
        """Session should be mutable (it tracks current state)."""
        session = Session()
        session.current_job_id = "job-abc123"
        assert session.current_job_id == "job-abc123"
