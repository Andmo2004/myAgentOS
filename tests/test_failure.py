"""Unit tests for Failure Classifier, Stagnation Detector, and Healing (§14, AUD-012)."""

import pytest

from myagentos.core.models.event import EventName
from myagentos.core.models.failure import (
    FailureAction,
    FailureCode,
    JobLimits,
    ObservedFailure,
)
from myagentos.failure.classifier import FailureClassifier
from myagentos.failure.fixtures import FAILURE_FIXTURES, FailureFixture
from myagentos.failure.healing import HealingCoordinator
from myagentos.failure.stagnation import StagnationDetector
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway


@pytest.mark.parametrize("fixture", FAILURE_FIXTURES, ids=lambda f: f.name)
def test_aud_012_failure_fixtures_classification_and_action(fixture: FailureFixture) -> None:
    """AUD-012: observed failure -> expected FailureCode -> expected FSM action and event."""
    classifier = FailureClassifier()
    code = classifier.classify(fixture.observed)
    assert code == fixture.expected_code, (
        f"Failed for {fixture.name}: expected {fixture.expected_code}, got {code}"
    )

    coordinator = HealingCoordinator(classifier=classifier)
    decision = coordinator.evaluate(job_id=f"job-{fixture.name}", observed=fixture.observed)

    assert decision.failure_record.code == fixture.expected_code
    assert decision.action == fixture.expected_action
    assert decision.fsm_event == fixture.expected_event


def test_failure_classifier_llm_tie_breaker() -> None:
    """Verifies that ambiguous traces invoke the LLM tie breaker strictly within the closed enum."""

    class TieBreakerAdapter(ProviderAdapter):
        def generate(
            self,
            messages: list[LLMMessage],
            model_id: str,
            temperature: float = 0.0,
            response_schema: type | None = None,
        ) -> LLMResponse:
            return LLMResponse(
                content="SYNTAX_ERROR", model_id=model_id, input_tokens=10, output_tokens=5
            )

    gateway = ModelGateway()
    gateway.register_adapter("mock", TieBreakerAdapter())

    classifier = FailureClassifier(gateway=gateway, model_id="mock")
    ambiguous = ObservedFailure(
        stage="COMPILE",
        exit_code=1,
        raw_output="Unexpected internal builder token parsing failure in mysterious format",
    )
    code = classifier.classify(ambiguous)
    assert code == FailureCode.SYNTAX_ERROR


def test_failure_classifier_unknown_fallback() -> None:
    """Verifies fallback to UNKNOWN when no pattern matches and no tie breaker succeeds."""
    classifier = FailureClassifier()
    strange_error = ObservedFailure(
        stage="CUSTOM_PHASE",
        exit_code=1,
        raw_output="Something completely unclassifiable happened with code 999",
    )
    assert classifier.classify(strange_error) == FailureCode.UNKNOWN


def test_stagnation_detector_identical_diff() -> None:
    """AUD-012 & §14.3: Detects stagnation when patch diffs are identical across attempts."""
    detector = StagnationDetector()
    diff = """
    --- a/file.py
    +++ b/file.py
    @@ -1,3 +1,3 @@
    -foo
    +bar
    """
    detector.record_attempt(job_id="job-stag-1", attempt_number=1, diff_output=diff)
    res1 = detector.check_stagnation("job-stag-1")
    assert not res1.stagnated

    detector.record_attempt(job_id="job-stag-1", attempt_number=2, diff_output=diff)
    res2 = detector.check_stagnation("job-stag-1")
    assert res2.stagnated
    assert "Identical patch diff" in res2.reason


def test_stagnation_detector_identical_test_failures() -> None:
    """AUD-012 & §14.3: Detects stagnation when identical tests fail with matching diagnostics."""
    detector = StagnationDetector()
    failed_tests = {"test_calc", "test_math"}
    diag = "AssertionError: 4 != 5 in 0.02s at 0x7fff line 12"

    detector.record_attempt(
        job_id="job-stag-2",
        attempt_number=1,
        failed_tests=failed_tests,
        diagnostic_output=diag,
    )
    res1 = detector.check_stagnation("job-stag-2")
    assert not res1.stagnated

    # Attempt 2: Same failed tests, slightly different timestamp/memory address (normalized)
    diag2 = "AssertionError: 4 != 5 in 0.09s at 0x9bbb line 12"
    detector.record_attempt(
        job_id="job-stag-2",
        attempt_number=2,
        failed_tests=failed_tests,
        diagnostic_output=diag2,
    )
    res2 = detector.check_stagnation("job-stag-2")
    assert res2.stagnated
    assert "failed consecutive attempts" in res2.reason


def test_healing_coordinator_hard_limit_exceeded() -> None:
    """§14.2: Enforces hard attempt limits per job."""
    limits = JobLimits(max_attempts=2)
    coordinator = HealingCoordinator(limits=limits)
    obs = ObservedFailure(stage="TEST", exit_code=1, raw_output="AssertionError: failed")

    d1 = coordinator.evaluate(job_id="job-limits", observed=obs, diff_output="diff1")
    assert d1.action == FailureAction.RETRY
    assert d1.can_retry

    d2 = coordinator.evaluate(job_id="job-limits", observed=obs, diff_output="diff2")
    assert d2.action == FailureAction.RETRY
    assert d2.can_retry

    # 3rd attempt exceeds max_attempts (2)
    d3 = coordinator.evaluate(job_id="job-limits", observed=obs, diff_output="diff3")
    assert d3.action == FailureAction.ESCALATED
    assert not d3.can_retry
    assert d3.fsm_event == EventName.ESCALATED


def test_healing_coordinator_syntax_error_limit() -> None:
    """§14.1 Table: SYNTAX_ERROR has max 2 attempts before escalation."""
    coordinator = HealingCoordinator()
    syntax_obs = ObservedFailure(
        stage="COMPILE", exit_code=1, raw_output="SyntaxError: invalid syntax"
    )

    d1 = coordinator.evaluate(job_id="job-syn", observed=syntax_obs, diff_output="diff1")
    assert d1.action == FailureAction.RETRY

    d2 = coordinator.evaluate(job_id="job-syn", observed=syntax_obs, diff_output="diff2")
    assert d2.action == FailureAction.RETRY

    # 3rd syntax error exceeds max_occurrences (2)
    d3 = coordinator.evaluate(job_id="job-syn", observed=syntax_obs, diff_output="diff3")
    assert d3.action == FailureAction.ESCALATED
    assert not d3.can_retry
    assert d3.fsm_event == EventName.ESCALATED
