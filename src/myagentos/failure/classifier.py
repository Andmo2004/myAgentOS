"""Deterministic failure classifier categorizing errors into a closed enum (§14.1)."""

import re
from typing import ClassVar

from myagentos.core.models.failure import FailureCode, ObservedFailure
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway


class FailureClassifier:
    """Deterministic, pattern-driven Failure Classifier (§14.1).

    Converts concrete, observed failure traces, stderr, compiler outputs,
    and process return codes into the closed system enum `FailureCode`.
    """

    # 1. Policy Violation Patterns (§5, §14.1)
    POLICY_PATTERNS: ClassVar[list[str]] = [
        r"PolicyViolation",
        r"POLICY_VIOLATION",
        r"CapabilityToken\s*(expired|invalid|violation)",
        r"forbidden by capability token",
        r"outside authorized scope",
        r"access.*is forbidden",
        r"sensitive path.*prohibited",
        r"egress\s+blocked",
        r"risk\s*level.*escalat(ed|ion)\s*denied",
        r"unauthorized tool call",
    ]

    # 2. Merge Conflict Patterns (§6, §14.1)
    MERGE_PATTERNS: ClassVar[list[str]] = [
        r"CONFLICT\s*\([a-z_-]+\):",
        r"Merge conflict in",
        r"Automatic merge failed",
        r"fix conflicts and then commit",
        r"unresolved conflict",
        r"patch does not apply cleanly",
        r"error: patch failed",
        r"would be overwritten by merge",
    ]

    # 3. Budget & Resource Quota Patterns (§14.1, §14.2)
    BUDGET_PATTERNS: ClassVar[list[str]] = [
        r"BUDGET_EXHAUSTED",
        r"BUDGET_PAUSED",
        r"token budget exceeded",
        r"max cost.*exceeded",
        r"insufficient token(s)?",
        r"quota exceeded",
        r"RateLimitError.*quota",
    ]

    # 4. Review Rejected Patterns (§14.1, §15)
    REVIEW_PATTERNS: ClassVar[list[str]] = [
        r"REVIEW_REJECTED",
        r"review\s*status\s*:\s*rejected",
        r"reviewer\s*rejected\s*changes",
        r"independent\s*review\s*failed",
        r"security\s*vulnerability\s*detected\s*by\s*reviewer",
        r"quality\s*gate\s*failed\s*in\s*review",
    ]

    # 5. Environment & Sandbox Patterns (§12, §14.1)
    ENVIRONMENT_PATTERNS: ClassVar[list[str]] = [
        r"Cannot connect to the Docker daemon",
        r"DockerException",
        r"docker:\s*error during connect",
        r"container exited with status 137",
        r"OOMKilled",
        r"PermissionError:\s*\[Errno 13\]\s*Permission denied",
        r"No space left on device",
        r"Read-only file system",
        r"command not found",
        r"/bin/sh:.*not found",
        r"exec:.*executable file not found",
        r"ConnectionRefusedError:\s*\[Errno 61\]",
        r"sandbox launch failed",
    ]

    # 6. Syntax Error Patterns (§14.1)
    SYNTAX_PATTERNS: ClassVar[list[str]] = [
        r"SyntaxError\b",
        r"IndentationError\b",
        r"TabError\b",
        r"invalid syntax",
        r"expected an indented block",
        r"TokenError",
        r"unindent does not match any outer indentation level",
        r"syntax error",
        r"failed to compile",
        r"parse error",
    ]

    # 7. Context Missing Patterns (§9.3, §14.1)
    CONTEXT_MISSING_PATTERNS: ClassVar[list[str]] = [
        r"NameError:\s*name\s*['\"].*['\"]\s*is not defined",
        r"UnboundLocalError:\s*local variable.*referenced before assignment",
        r"ModuleNotFoundError:\s*No module named ['\"](src|myagentos|\..*)['\"]",
        r"ImportError:\s*cannot import name.*from ['\"](src|myagentos|\..*)['\"]",
        r"FileNotFoundError:\s*\[Errno 2\]\s*No such file or directory:.*(src|docs|tests)",
        r"AttributeError:\s*module ['\"](src|myagentos)[\w\.]*['\"]\s*has no attribute",
    ]

    # 8. Dependency Error Patterns (§11.6, §14.1)
    DEPENDENCY_PATTERNS: ClassVar[list[str]] = [
        r"ModuleNotFoundError:\s*No module named\b",
        r"ImportError:\s*cannot import name\b",
        r"Could not find a version that satisfies the requirement",
        r"No matching distribution found",
        r"ResolutionImpossible",
        r"uv pip install.*failed",
        r"pip install.*failed",
        r"DLL load failed",
        r"cannot open shared object file",
    ]

    # 9. Flaky Test Patterns (§13.7, §14.1)
    FLAKY_PATTERNS: ClassVar[list[str]] = [
        r"FLAKY_TEST",
        r"flaky\s*test\s*detected",
        r"test passed on rerun but failed initially",
        r"intermittent socket timeout",
        r"intermittent assertion failure",
    ]

    # 10. Test Failure Patterns (§13, §14.1)
    TEST_FAILURE_PATTERNS: ClassVar[list[str]] = [
        r"AssertionError\b",
        r"FAILED\s+tests/",
        r"FAILED\s+.*::test_",
        r"=== FAILURES ===",
        r"assert\s+.*==.*",
        r"assert\s+not\b",
        r"pytest:.*command failed",
        r"tests?\s+failed",
    ]

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        model_id: str = "mock",
    ) -> None:
        self.gateway = gateway
        self.model_id = model_id

    def classify(self, observed: ObservedFailure) -> FailureCode:
        """Deterministically classifies an observed failure into `FailureCode` (§14.1)."""
        text = f"{observed.raw_output} {observed.error_type or ''} {observed.metadata}"
        stage = observed.stage.upper()

        # Stage-guided overrides
        if stage in ("POLICY", "POLICY_VALIDATION") or self._matches(text, self.POLICY_PATTERNS):
            if self._matches(text, self.POLICY_PATTERNS):
                return FailureCode.POLICY_VIOLATION

        if stage in ("MERGE", "MERGE_CHECK") or self._matches(text, self.MERGE_PATTERNS):
            if self._matches(text, self.MERGE_PATTERNS):
                return FailureCode.MERGE_CONFLICT

        if stage in ("REVIEW", "INDEPENDENT_REVIEW") or self._matches(text, self.REVIEW_PATTERNS):
            if self._matches(text, self.REVIEW_PATTERNS):
                return FailureCode.REVIEW_REJECTED

        if self._matches(text, self.BUDGET_PATTERNS):
            return FailureCode.BUDGET_EXHAUSTED

        if self._matches(text, self.ENVIRONMENT_PATTERNS):
            return FailureCode.ENVIRONMENT_ERROR

        if stage in ("COMPILE", "SYNTAX") or self._matches(text, self.SYNTAX_PATTERNS):
            if self._matches(text, self.SYNTAX_PATTERNS):
                return FailureCode.SYNTAX_ERROR

        # Check Context Missing before generic Dependency Error
        if self._matches(text, self.CONTEXT_MISSING_PATTERNS):
            return FailureCode.CONTEXT_MISSING

        if self._matches(text, self.DEPENDENCY_PATTERNS):
            return FailureCode.DEPENDENCY_ERROR

        if self._matches(text, self.FLAKY_PATTERNS):
            return FailureCode.FLAKY_TEST

        if stage in ("TEST", "VERIFY", "PROTECTED_TESTS") or self._matches(
            text, self.TEST_FAILURE_PATTERNS
        ):
            if self._matches(text, self.TEST_FAILURE_PATTERNS):
                return FailureCode.TEST_FAILURE
            # If in TEST or VERIFY stage and process failed, default to TEST_FAILURE
            if observed.exit_code != 0:
                return FailureCode.TEST_FAILURE

        # Optional LLM tie-breaker strictly constrained to closed enum (§14.1)
        if self.gateway is not None:
            tie_code = self._llm_tie_breaker(observed)
            if tie_code is not None:
                return tie_code

        return FailureCode.UNKNOWN

    def _matches(self, text: str, patterns: list[str]) -> bool:
        """Evaluates whether any regex pattern matches the text (case-insensitive)."""
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False

    def _llm_tie_breaker(self, observed: ObservedFailure) -> FailureCode | None:
        """Dispatches ambiguous failure traces to an LLM strictly constrained to enum."""
        if self.gateway is None:
            return None
        prompt = (
            "Classify the following software execution failure into exactly "
            "ONE of these closed classes:\n"
            f"{', '.join(f.value for f in FailureCode)}\n\n"
            f"Stage: {observed.stage}\n"
            f"Exit Code: {observed.exit_code}\n"
            f"Output:\n{observed.raw_output[:800]}\n\n"
            f"Return ONLY the exact failure code name in all uppercase."
        )
        try:
            resp = self.gateway.generate(
                messages=[LLMMessage(role="user", content=prompt)],
                model_id=self.model_id,
                temperature=0.0,
            )
            raw = resp.content.strip().replace("`", "").strip()
            if raw in FailureCode.__members__:
                return FailureCode(raw)
        except Exception:
            pass
        return None
