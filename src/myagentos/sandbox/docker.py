"""Docker rootless sandbox driver implementing strict Zone Z4 isolation (§11)."""

import shlex
import subprocess
import time
from pathlib import Path

from myagentos.core.errors import SandboxExecutionError, SandboxUnavailableError
from myagentos.sandbox.base import ExecutionLimits, ExecutionResult, SandboxDriver

# Forbidden host directories that must NEVER be mounted into the sandbox (§11.1)
FORBIDDEN_HOST_PATHS = [
    ".ssh",
    ".aws",
    ".config",
    "docker.sock",
    "id_rsa",
    "id_ed25519",
]


class DockerSandboxDriver(SandboxDriver):
    """Hardened Docker sandbox driver with zero network egress and dropped capabilities (§11.1)."""

    def __init__(self, image: str = "python:3.12-slim") -> None:
        self.image = image

    @classmethod
    def is_available(cls) -> bool:
        """Checks if Docker daemon is installed and accessible (§11)."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def build_docker_args(
        self,
        worktree_path: Path,
        limits: ExecutionLimits,
        env_vars: dict[str, str] | None = None,
    ) -> list[str]:
        """Constructs the hardened docker run command with normative security flags (§11.1)."""
        resolved_wt = worktree_path.resolve()

        # Security assertion: ensure worktree path does not leak forbidden paths
        for forbidden in FORBIDDEN_HOST_PATHS:
            if forbidden in str(resolved_wt):
                raise SandboxExecutionError(
                    f"Attempted to mount path containing forbidden secret marker: {forbidden}"
                )

        args = [
            "docker",
            "run",
            "--rm",
            # Mandatory network isolation: only loopback (§4, §11.1)
            "--network",
            "none",
            # Drop all kernel capabilities (§11.1)
            "--cap-drop=ALL",
            # Prevent privilege escalation (§11.1)
            "--security-opt=no-new-privileges",
            # Read-only root filesystem (§11.1)
            "--read-only",
            # Resource constraints (§11.3)
            f"--cpus={limits.max_cpus}",
            f"--memory={limits.max_memory_mb}m",
            # Ephemeral mounts (§11.5)
            "-v",
            f"{resolved_wt}:/source:ro",
            "--tmpfs",
            "/build:rw,exec,size=512m",
            "--tmpfs",
            "/tmp:rw,size=128m",
            "-w",
            "/source",
        ]

        if env_vars:
            for k, v in env_vars.items():
                args.extend(["-e", f"{k}={v}"])

        args.append(self.image)
        return args

    def run_command(
        self,
        command: str | list[str],
        worktree_path: Path,
        limits: ExecutionLimits | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        if not self.is_available():
            raise SandboxUnavailableError(
                "Docker daemon is not available or not running. "
                "Execution in Zone Z4 requires an accessible Docker daemon (AGF-002)."
            )

        active_limits = limits or ExecutionLimits()
        base_args = self.build_docker_args(
            worktree_path=worktree_path,
            limits=active_limits,
            env_vars=env_vars,
        )

        if isinstance(command, list):
            cmd_args = list(command)
        else:
            try:
                cmd_args = shlex.split(command)
            except ValueError:
                cmd_args = command.strip().split()

        # Run binary directly without sh -c to prevent command chaining (AGF-002)
        full_cmd = base_args + cmd_args
        start_time = time.monotonic()

        try:
            res = subprocess.run(
                full_cmd,
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
                stderr="Execution timed out in Code Sandbox",
                duration_seconds=duration,
                timed_out=True,
            )
        except Exception as ex:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr=f"Sandbox error: {ex}",
                duration_seconds=duration,
                timed_out=False,
            )
