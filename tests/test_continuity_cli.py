"""Tests for the CLI continue command and actions."""

from pathlib import Path
from unittest.mock import patch

from myagentos.cli import cmd_continue


def test_cli_continue_run_and_report(tmp_path: Path) -> None:
    """Verifies that cmd_continue generates packs, prints findings and reports."""
    # Run audit on tmp_path
    cmd_continue(action="run", repo_path=str(tmp_path))

    # Verify directory created under .myagentos/projects
    proj_dir = tmp_path / ".myagentos" / "projects" / tmp_path.name / "continuity"
    assert proj_dir.is_dir()
    snaps = list(proj_dir.iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "CONTINUATION_CONTEXT.md").is_file()
    assert (snaps[0] / "findings.json").is_file()

    # Test report action without raising
    cmd_continue(action="report", repo_path=str(tmp_path))

    # Test findings action without raising
    cmd_continue(action="findings", repo_path=str(tmp_path))


def test_cli_continue_dynamic_flag(tmp_path: Path) -> None:
    """Verifies that cmd_continue with dynamic=True runs without errors."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "42 passed in 0.5s"
        mock_run.return_value.stderr = ""

        # Create dummy tests dir
        (tmp_path / "tests").mkdir()
        cmd_continue(action="run", repo_path=str(tmp_path), dynamic=True)

        proj_dir = tmp_path / ".myagentos" / "projects" / tmp_path.name / "continuity"
        snaps = list(proj_dir.iterdir())
        assert (snaps[0] / "baseline.json").is_file()
