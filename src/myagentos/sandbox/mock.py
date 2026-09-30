"""Mock and subprocess sandbox driver for fast local execution and tests without Docker."""

import subprocess
import time
from pathlib import Path

from myagentos.sandbox.base import ExecutionLimits, ExecutionResult, SandboxDriver


class MockSandboxDriver(SandboxDriver):
    """In-process and subprocess sandbox driver for local macOS test suites."""

    def __init__(self, use_real_subprocess: bool = True) -> None:
        self.use_real_subprocess = use_real_subprocess
        self.mocked_commands: dict[str, ExecutionResult] = {}
        self.executed_commands: list[str] = []

    def register_mock(
        self,
        command_prefix: str,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        duration_seconds: float = 0.05,
    ) -> None:
        """Preconfigures deterministic output for a specific command."""
        self.mocked_commands[command_prefix] = ExecutionResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
            timed_out=False,
        )

    def run_command(
        self,
        command: str,
        worktree_path: Path,
        limits: ExecutionLimits | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        self.executed_commands.append(command)
        active_limits = limits or ExecutionLimits()

        # Check registered mocks first
        for prefix, result in self.mocked_commands.items():
            if command.startswith(prefix) or command == prefix:
                return result

        if not self.use_real_subprocess:
            return ExecutionResult(
                exit_code=0,
                stdout="Mock command succeeded",
                stderr="",
                duration_seconds=0.01,
                timed_out=False,
            )

        start_time = time.monotonic()
        try:
            # Clean minimal environment to prevent secret leaking
            env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"}
            if env_vars:
                env.update(env_vars)

            res = subprocess.run(
                command,
                shell=True,
                cwd=str(worktree_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=active_limits.timeout_seconds,
                check=False,
            )
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_seconds=duration,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout=e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                stderr="Mock execution timed out",
                duration_seconds=duration,
                timed_out=True,
            )
