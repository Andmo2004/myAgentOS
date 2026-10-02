"""myagentos core exceptions hierarchy."""


class MyAgentOSError(Exception):
    """Base exception for all myagentos errors."""


AgenticOSError = MyAgentOSError


class RiskMonotonicityError(MyAgentOSError):
    """Raised when an attempt is made to de-escalate risk within a job."""


RiskMonotonicityViolation = RiskMonotonicityError


class PolicyViolationError(MyAgentOSError):
    """Raised when an operation violates security policy or capability token boundaries."""


class ScopeViolationError(PolicyViolationError):
    """Raised when a patch or tool accesses paths outside the authorized scope."""


class HashChainCorruptionError(MyAgentOSError):
    """Raised when event hash verification fails in the append-only log."""


class StalePlanError(MyAgentOSError):
    """Raised when git changes invalidate an approved plan (§8.4)."""


class BudgetExhaustedError(MyAgentOSError):
    """Raised when USD budget limit or step limit is exhausted."""


class StateTransitionError(MyAgentOSError):
    """Raised when an illegal FSM transition is attempted."""


class SandboxExecutionError(MyAgentOSError):
    """Raised when sandbox execution fails due to environment or resource limits."""


class SandboxUnavailableError(SandboxExecutionError):
    """Raised when an isolated sandbox driver is required but unavailable (§11)."""


class PathEscapeError(PolicyViolationError):
    """Raised when a path attempts directory traversal or escapes authorized boundary (§10)."""


class SymlinkDisallowedError(PolicyViolationError):
    """Raised when an operation encounters an untrusted symlink (§10.3, AGF-003)."""


class ApprovalRequiredError(PolicyViolationError):
    """Raised when an operation requires approval that has not been granted (§8, AGF-005)."""


class PatchApplicationError(MyAgentOSError):
    """Raised when applying a patch set fails or cannot maintain integrity (AGF-006)."""
