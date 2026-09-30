"""Unit tests for the Sandbox drivers and execution constraints."""

from pathlib import Path

import pytest

from myagentos.core.errors import SandboxExecutionError
from myagentos.sandbox import (
    DockerSandboxDriver,
    ExecutionLimits,
    MockSandboxDriver,
)


def test_docker_sandbox_build_args_security_flags(tmp_path: Path) -> None:
    driver = DockerSandboxDriver(image="python:3.12-slim")
    limits = ExecutionLimits(timeout_seconds=30, max_memory_mb=512, max_cpus=1.5)

    args = driver.build_docker_args(worktree_path=tmp_path, limits=limits)

    # Validate normative security constraints (§11.1)
    assert "--network" in args and args[args.index("--network") + 1] == "none"
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges" in args
    assert "--read-only" in args
    assert "--cpus=1.5" in args
    assert "--memory=512m" in args
    assert any("/source:ro" in arg for arg in args)
    assert any("/build:rw" in arg for arg in args)


def test_docker_sandbox_forbidden_mount_detection(tmp_path: Path) -> None:
    driver = DockerSandboxDriver()
    limits = ExecutionLimits()

    leaky_dir = tmp_path / ".ssh" / "repo"
    leaky_dir.mkdir(parents=True)

    with pytest.raises(SandboxExecutionError):
        driver.build_docker_args(worktree_path=leaky_dir, limits=limits)


def test_mock_sandbox_driver_deterministic_and_subprocess(tmp_path: Path) -> None:
    driver = MockSandboxDriver(use_real_subprocess=True)

    # 1. Registered mock returns exact response
    driver.register_mock("pytest", exit_code=0, stdout="10 passed")
    res = driver.run_command("pytest tests/unit", worktree_path=tmp_path)
    assert res.exit_code == 0
    assert "10 passed" in res.stdout

    # 2. Real simple subprocess execution
    res_real = driver.run_command("echo 'sandboxed'", worktree_path=tmp_path)
    assert res_real.exit_code == 0
    assert "sandboxed" in res_real.stdout.strip()
