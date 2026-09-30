"""Stagnation detection across execution attempts according to §14.3."""

import hashlib
import re
from dataclasses import dataclass

from myagentos.core.models.failure import StagnationResult


@dataclass
class AttemptSnapshot:
    """Historical snapshot of an attempt for stagnation analysis."""

    attempt_number: int
    failed_tests: set[str]
    diag_hash: str
    diff_hash: str
    cost_usd: float = 0.0


class StagnationDetector:
    """Detects lack of progress or looping in worker attempts (§14.3)."""

    def __init__(self, test_threshold: int = 2) -> None:
        self.test_threshold = test_threshold
        self._history: dict[str, list[AttemptSnapshot]] = {}

    def record_attempt(
        self,
        job_id: str,
        attempt_number: int,
        failed_tests: set[str] | None = None,
        diagnostic_output: str = "",
        diff_output: str = "",
        cost_usd: float = 0.0,
    ) -> AttemptSnapshot:
        """Records an attempt's telemetry for stagnation checking."""
        diag_norm = self._normalize_diagnostics(diagnostic_output)
        diff_norm = self._normalize_diff(diff_output)

        snapshot = AttemptSnapshot(
            attempt_number=attempt_number,
            failed_tests=set(failed_tests or []),
            diag_hash=hashlib.sha256(diag_norm.encode("utf-8")).hexdigest(),
            diff_hash=hashlib.sha256(diff_norm.encode("utf-8")).hexdigest() if diff_norm else "",
            cost_usd=cost_usd,
        )
        if job_id not in self._history:
            self._history[job_id] = []
        self._history[job_id].append(snapshot)
        return snapshot

    def check_stagnation(self, job_id: str) -> StagnationResult:
        """Evaluates whether the job has stagnated (§14.3)."""
        history = self._history.get(job_id, [])
        if len(history) < 2:
            return StagnationResult(
                stagnated=False, reason="Insufficient history", consecutive_matches=0
            )

        prev = history[-2]
        curr = history[-1]

        # 1. Diff Stagnation: Diff of attempt N is identical to attempt N-1 (§14.3)
        if curr.diff_hash and curr.diff_hash == prev.diff_hash:
            return StagnationResult(
                stagnated=True,
                reason="Identical patch diff generated across consecutive attempts (§14.3)",
                consecutive_matches=2,
            )

        # 2. Test Stagnation: Same set of tests fail 2 consecutive attempts (§14.3)
        if curr.failed_tests and curr.failed_tests == prev.failed_tests:
            if curr.diag_hash == prev.diag_hash:
                return StagnationResult(
                    stagnated=True,
                    reason=(
                        f"Same set of {len(curr.failed_tests)} test(s) failed consecutive "
                        f"attempts with identical diagnostics (§14.3)"
                    ),
                    consecutive_matches=2,
                )

        return StagnationResult(stagnated=False, reason="Progress detected", consecutive_matches=0)

    def reset(self, job_id: str) -> None:
        """Clears recorded history for a job."""
        if job_id in self._history:
            del self._history[job_id]

    def _normalize_diff(self, diff: str) -> str:
        """Normalizes unified diff by removing timestamps and line index variations."""
        lines: list[str] = []
        for line in diff.splitlines():
            line_s = line.strip()
            if line_s.startswith(("---", "+++", "@@")):
                continue
            lines.append(line_s)
        return "\n".join(lines).strip()

    def _normalize_diagnostics(self, diag: str) -> str:
        """Normalizes diagnostics by stripping execution runtimes and memory addresses."""
        cleaned = re.sub(r"in \d+\.\d+s", "in <TIME>", diag)
        cleaned = re.sub(r"at 0x[0-9a-fA-F]+", "at <ADDR>", cleaned)
        cleaned = re.sub(r"line \d+", "line <LINE>", cleaned)
        return cleaned.strip()
