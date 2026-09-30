"""Standard failure fixtures for validation and testing as specified in AUD-012."""

from dataclasses import dataclass

from myagentos.core.models.event import EventName
from myagentos.core.models.failure import FailureAction, FailureCode, ObservedFailure


@dataclass(frozen=True)
class FailureFixture:
    """Standardized failure fixture for automated verification (§14, AUD-012)."""

    name: str
    description: str
    observed: ObservedFailure
    expected_code: FailureCode
    expected_action: FailureAction
    expected_event: EventName


FAILURE_FIXTURES: list[FailureFixture] = [
    # 1. Syntax Fixture
    FailureFixture(
        name="syntax_error_python",
        description="Python syntax error with invalid indentation/syntax",
        observed=ObservedFailure(
            stage="COMPILE",
            exit_code=1,
            raw_output=(
                "  File 'src/calculator.py', line 14\n"
                "    def add(a, b)\n"
                "                 ^\n"
                "SyntaxError: invalid syntax"
            ),
            error_type="SyntaxError",
            target_path="src/calculator.py",
        ),
        expected_code=FailureCode.SYNTAX_ERROR,
        expected_action=FailureAction.RETRY,
        expected_event=EventName.RETRY_SCHEDULED,
    ),
    # 2. Test Failure Fixture
    FailureFixture(
        name="pytest_assertion_failure",
        description="Pytest assertion error during test execution",
        observed=ObservedFailure(
            stage="TEST",
            exit_code=1,
            raw_output=(
                "FAILED tests/test_calc.py::test_addition - AssertionError: assert 4 != 5\n"
                "E   assert 4 == 5\n"
                "=== 1 failed, 12 passed in 0.42s ==="
            ),
            error_type="AssertionError",
            target_path="tests/test_calc.py",
        ),
        expected_code=FailureCode.TEST_FAILURE,
        expected_action=FailureAction.RETRY,
        expected_event=EventName.RETRY_SCHEDULED,
    ),
    # 3. Environment Fixture
    FailureFixture(
        name="docker_daemon_unavailable",
        description="Sandbox startup failure due to missing Docker daemon or permissions",
        observed=ObservedFailure(
            stage="SANDBOX",
            exit_code=1,
            raw_output=(
                "DockerException: Error while fetching server API version: "
                "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                "Is the docker daemon running?"
            ),
            error_type="DockerException",
        ),
        expected_code=FailureCode.ENVIRONMENT_ERROR,
        expected_action=FailureAction.ENV_REPAIR,
        expected_event=EventName.ENV_REPAIR_STARTED,
    ),
    # 4. Dependency Fixture
    FailureFixture(
        name="external_dependency_missing",
        description="External third-party module not installed in environment",
        observed=ObservedFailure(
            stage="TEST",
            exit_code=1,
            raw_output="ModuleNotFoundError: No module named 'numpy'",
            error_type="ModuleNotFoundError",
        ),
        expected_code=FailureCode.DEPENDENCY_ERROR,
        expected_action=FailureAction.ESCALATED,
        expected_event=EventName.ESCALATED,
    ),
    # 5. Policy Fixture
    FailureFixture(
        name="capability_token_forbidden_path",
        description="PolicyEngine blocking unauthorized path write outside token scope",
        observed=ObservedFailure(
            stage="POLICY_VALIDATION",
            exit_code=1,
            raw_output=(
                "PolicyViolation: Access to '.env.production' is forbidden by capability token. "
                "Sensitive path prohibited outside authorized scope."
            ),
            error_type="PolicyViolation",
            target_path=".env.production",
        ),
        expected_code=FailureCode.POLICY_VIOLATION,
        expected_action=FailureAction.STOP,
        expected_event=EventName.POLICY_VIOLATION,
    ),
    # 6. Merge Conflict Fixture
    FailureFixture(
        name="git_merge_conflict",
        description="Git merge conflict when merging worktree branch into repository base",
        observed=ObservedFailure(
            stage="MERGE_CHECK",
            exit_code=1,
            raw_output=(
                "CONFLICT (content): Merge conflict in src/core/main.py\n"
                "Automatic merge failed; fix conflicts and then commit the result."
            ),
            error_type="MergeConflict",
            target_path="src/core/main.py",
        ),
        expected_code=FailureCode.MERGE_CONFLICT,
        expected_action=FailureAction.STOP,
        expected_event=EventName.MERGE_CONFLICT,
    ),
    # 7. Review Rejected Fixture
    FailureFixture(
        name="independent_reviewer_rejection",
        description="Independent Reviewer flagging security or architectural defects",
        observed=ObservedFailure(
            stage="INDEPENDENT_REVIEW",
            exit_code=1,
            raw_output=(
                "REVIEW_REJECTED: Security vulnerability detected by reviewer. "
                "Hardcoded credentials found in src/auth.py: line 42."
            ),
            error_type="ReviewRejected",
            target_path="src/auth.py",
        ),
        expected_code=FailureCode.REVIEW_REJECTED,
        expected_action=FailureAction.RETRY,
        expected_event=EventName.RETRY_SCHEDULED,
    ),
    # 8. Budget Fixture
    FailureFixture(
        name="token_budget_exhaustion",
        description="Execution halted due to exceeding monetary / token allowance",
        observed=ObservedFailure(
            stage="BUDGET",
            exit_code=1,
            raw_output=(
                "BUDGET_EXHAUSTED: Token budget exceeded for job. "
                "Max cost of 10.00 USD exceeded."
            ),
            error_type="BudgetExhausted",
        ),
        expected_code=FailureCode.BUDGET_EXHAUSTED,
        expected_action=FailureAction.STOP,
        expected_event=EventName.BUDGET_PAUSED,
    ),
    # 9. Context Missing Fixture
    FailureFixture(
        name="internal_symbol_undefined",
        description="Internal symbol or workspace module reference missing from worker context",
        observed=ObservedFailure(
            stage="EXECUTE",
            exit_code=1,
            raw_output="NameError: name 'calculate_tax_rate' is not defined",
            error_type="NameError",
        ),
        expected_code=FailureCode.CONTEXT_MISSING,
        expected_action=FailureAction.CONTEXT_EXPANSION,
        expected_event=EventName.CONTEXT_EXPANDED,
    ),
    # 10. Flaky Test Fixture
    FailureFixture(
        name="flaky_test_intermittent",
        description="Intermittent failure identified as flaky test candidate",
        observed=ObservedFailure(
            stage="VERIFY",
            exit_code=1,
            raw_output=(
                "FLAKY_TEST: test passed on rerun but failed initially "
                "due to intermittent socket timeout"
            ),
            error_type="FlakyTest",
        ),
        expected_code=FailureCode.FLAKY_TEST,
        expected_action=FailureAction.ESCALATED,
        expected_event=EventName.ESCALATED,
    ),
]
