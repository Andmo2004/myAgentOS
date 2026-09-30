"""myagentos core exceptions hierarchy."""


class MyAgentOSError(Exception):
    """Base exception for all myagentos errors."""


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
