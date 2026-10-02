"""Mock and subprocess sandbox driver for fast local execution and tests without Docker."""

import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

from myagentos.sandbox.base import ExecutionLimits, ExecutionResult, SandboxDriver


class MockSandboxDriver(SandboxDriver):
    """In-process and subprocess sandbox driver for local macOS test suites.

    By default, this driver is purely simulated and does NOT execute host processes (AGF-002).
    """

    def __init__(self, use_real_subprocess: bool = False) -> None:
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
        command: str | list[str],
        worktree_path: Path,
        limits: ExecutionLimits | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        if isinstance(command, list):
            cmd_str = " ".join(shlex.quote(c) for c in command)
            cmd_args = list(command)
        else:
            cmd_str = command
            try:
                cmd_args = shlex.split(command)
            except ValueError:
                cmd_args = command.strip().split()

        self.executed_commands.append(cmd_str)
        active_limits = limits or ExecutionLimits()

        # Check registered mocks first
        for prefix, result in self.mocked_commands.items():
            if (
                cmd_str.startswith(prefix)
                or cmd_str == prefix
                or (cmd_args and cmd_args[0] == prefix)
            ):
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
        # Clean minimal environment to prevent secret leaking
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"}
        if env_vars:
            env.update(env_vars)

        try:
            # Use structured command without shell interpretation (AGF-002)
            # Use start_new_session=True to establish a new process group for clean termination
            proc = subprocess.Popen(
                cmd_args,
                shell=False,
                cwd=str(worktree_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=active_limits.timeout_seconds)
            except subprocess.TimeoutExpired:
                # Terminate entire process group on timeout (AGF-002)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                stdout, stderr = proc.communicate()
                duration = time.monotonic() - start_time
                return ExecutionResult(
                    exit_code=-1,
                    stdout=stdout[:100_000] if stdout else "",
                    stderr="Subprocess execution timed out",
                    duration_seconds=duration,
                    timed_out=True,
                )

            duration = time.monotonic() - start_time
            # Cap output to avoid memory exhaustion
            return ExecutionResult(
                exit_code=proc.returncode,
                stdout=stdout[:500_000] if stdout else "",
                stderr=stderr[:500_000] if stderr else "",
                duration_seconds=duration,
                timed_out=False,
            )
        except Exception as ex:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Subprocess execution error: {ex}",
                duration_seconds=duration,
                timed_out=False,
            )
