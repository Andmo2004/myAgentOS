"""Unit tests for the VerificationGuard and protected test harness integrity."""

import subprocess
from pathlib import Path

from myagentos.core.models.failure import FailureCode
from myagentos.sandbox import MockSandboxDriver
from myagentos.verification import (
    TestManifest,
    VerificationGuard,
    restore_protected_paths,
)


def _init_repo_with_protected_file(path: Path) -> tuple[str, str]:
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "g@os.dev"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Guard Tester"], cwd=str(path), check=True)

    # Protected file
    conftest = path / "conftest.py"
    conftest_content = "# Original protected harness\n"
    conftest.write_text(conftest_content, encoding="utf-8")

    src = path / "app.py"
    src.write_text("def app(): return True\n", encoding="utf-8")

    subprocess.run(["git", "add", "-A"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True)

    rev = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(path),
        capture_output=True,
        text=True,
        check=True,
    )
    return rev.stdout.strip(), conftest_content


def test_restore_protected_paths(tmp_path: Path) -> None:
    base_commit, orig_conftest = _init_repo_with_protected_file(tmp_path)

    # Worker attempts to tamper with protected conftest.py
    conftest_file = tmp_path / "conftest.py"
    conftest_file.write_text("# Tampered malicious harness\n", encoding="utf-8")

    # Run restoration
    restored = restore_protected_paths(
        worktree_path=tmp_path,
        base_commit=base_commit,
        protected_paths=["conftest.py"],
    )

    assert "conftest.py" in restored
    # File content must match original base_commit
    assert conftest_file.read_text(encoding="utf-8") == orig_conftest


def test_test_manifest_rules() -> None:
    manifest = TestManifest(
        baseline_test_ids={"test_1", "test_2", "test_3"},
        expected_new_test_ids={"test_4"},
    )

    # 1. Happy path: all run, none fail
    ok, err = manifest.validate_candidate(
        executed_test_ids={"test_1", "test_2", "test_3", "test_4"},
        failed_test_ids=set(),
        skipped_test_ids=set(),
    )
    assert ok is True
    assert err is None

    # 2. Silently deleted / missing test
    ok_miss, err_miss = manifest.validate_candidate(
        executed_test_ids={"test_1", "test_2"},
        failed_test_ids=set(),
        skipped_test_ids=set(),
    )
    assert ok_miss is False
    assert err_miss is not None
    assert "Missing expected tests" in err_miss

    # 3. Baseline test turned into skipped
    ok_skip, err_skip = manifest.validate_candidate(
        executed_test_ids={"test_1", "test_2", "test_3", "test_4"},
        failed_test_ids=set(),
        skipped_test_ids={"test_1"},
    )
    assert ok_skip is False
    assert err_skip is not None
    assert "cannot be turned into skipped" in err_skip


def test_verification_guard_pipeline(tmp_path: Path) -> None:
    base_commit, _ = _init_repo_with_protected_file(tmp_path)

    mock_driver = MockSandboxDriver(use_real_subprocess=False)
    guard = VerificationGuard(sandbox_driver=mock_driver)

    # 1. Happy path
    res = guard.verify(
        worktree_path=tmp_path,
        base_commit=base_commit,
        compile_cmd="python -m py_compile app.py",
        lint_cmd="ruff check app.py",
        project_test_cmd="pytest tests/",
    )
    assert res.passed is True
    assert res.failure_code is None
    assert res.stage_summaries.get("COMPILE") == "PASS"

    # 2. Compile failure
    mock_driver.register_mock(
        "python -m py_compile", exit_code=1, stderr="SyntaxError: invalid syntax"
    )
    res_fail = guard.verify(
        worktree_path=tmp_path,
        base_commit=base_commit,
        compile_cmd="python -m py_compile app.py",
    )
    assert res_fail.passed is False
    assert res_fail.failure_code == FailureCode.SYNTAX_ERROR
    assert "SyntaxError" in res_fail.diagnostics
