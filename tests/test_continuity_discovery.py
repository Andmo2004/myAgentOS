"""Tests for snapshot capture and deterministic static discovery."""

from pathlib import Path

from myagentos.continuity.discovery import run_static_discovery
from myagentos.continuity.models import EvidenceTier, FindingCode, FindingSeverity
from myagentos.continuity.snapshot import create_project_snapshot


def test_snapshot_current_repo() -> None:
    """Verifies that create_project_snapshot inspects the workspace repo."""
    repo_root = Path(__file__).parent.parent
    snapshot = create_project_snapshot(repo_root)

    assert snapshot.repository == repo_root.name
    assert snapshot.base_commit != ""
    assert len(snapshot.tracked_files) > 0
    assert "uv.lock" in snapshot.dependency_lock_hashes
    assert "python" in snapshot.toolchain_fingerprint
    assert len(snapshot.calculate_snapshot_hash()) == 64


def test_static_discovery_on_synthetic_repo(tmp_path: Path) -> None:
    """Verifies deterministic static discovery on a controlled repository."""
    # Setup synthetic project files
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "synthetic-app"
version = "0.1.0"
dependencies = [
    "fastapi>=0.100.0",
    "pytest>=8.0.0",
]

[project.scripts]
synthetic-cli = "synthetic_app.cli:main"
        """.strip()
    )

    src_dir = tmp_path / "src" / "synthetic_app"
    src_dir.mkdir(parents=True)
    init_file = src_dir / "__init__.py"
    init_file.write_text('"""Synthetic app package."""\n')

    cli_file = src_dir / "cli.py"
    cli_file.write_text(
        """
def main() -> None:
    print("hello")
        """.strip()
    )

    bad_module = src_dir / "bad.py"
    bad_module.write_text(
        """
from myagentos.non_existent_module import GhostSymbol

# TODO: implement real feature
# FIXME: fix this later
# TODO: refactor auth
# HACK: temporary workaround
# XXX: dangerous assumption

def broken_func() -> None:
    api_key = "sk-1234567890abcdef1234567890"
        """.strip()
    )

    # Fake snapshot
    snapshot = create_project_snapshot(tmp_path)

    arch_map, findings = run_static_discovery(tmp_path, snapshot)

    # 1. Architecture assertions
    assert "python" in arch_map.languages
    assert "fastapi" in arch_map.frameworks
    assert "pytest" in arch_map.frameworks
    assert any(e.path.endswith("cli.py") for e in arch_map.entrypoints)

    # 2. Findings assertions
    codes = [f.code for f in findings]

    # Secret detection (§33: Redacted!)
    secret_findings = [f for f in findings if f.code == FindingCode.SECRET_DETECTED]
    assert len(secret_findings) >= 1
    assert secret_findings[0].severity == FindingSeverity.HIGH
    ev = secret_findings[0].evidence[0]
    assert ev.kind == EvidenceTier.OBSERVED
    assert ev.observed_value is not None
    assert "..." in ev.observed_value
    assert "1234567890abcdef" not in ev.observed_value  # strictly redacted

    # Broken import
    broken_findings = [f for f in findings if f.code == FindingCode.BROKEN_IMPORT]
    assert len(broken_findings) >= 1
    assert broken_findings[0].severity == FindingSeverity.HIGH
    assert broken_findings[0].evidence[0].kind == EvidenceTier.DERIVED

    # TODO accumulation
    todo_findings = [f for f in findings if f.code == FindingCode.TODO_ACCUMULATION]
    assert len(todo_findings) == 1
    assert todo_findings[0].severity == FindingSeverity.INFO

    # Doc drift (missing README)
    assert FindingCode.DOC_DRIFT in codes
