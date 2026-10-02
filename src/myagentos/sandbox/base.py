"""Pluggable Sandbox interface and execution result models according to §11."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionLimits:
    """Resource bounds applied to sandbox execution (§11.3)."""

    timeout_seconds: int = 60
    max_memory_mb: int = 1024
    max_cpus: float = 2.0


@dataclass(frozen=True)
class ExecutionResult:
    """Output and status of a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxDriver(ABC):
    """Abstract base driver for isolated code and test execution (Zone Z4, §11)."""

    @abstractmethod
    def run_command(
        self,
        command: str | list[str],
        worktree_path: Path,
        limits: ExecutionLimits | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Executes a command inside the sandbox."""
        ...
