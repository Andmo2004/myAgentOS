"""Healing coordinator deciding failure actions, limits, and repair strategies (§14)."""


from myagentos.core.models.event import EventName
from myagentos.core.models.failure import (
    FAILURE_ACTION_MAP,
    FailureAction,
    FailureCode,
    FailureRecord,
    HealingDecision,
    JobLimits,
    ObservedFailure,
)
from myagentos.failure.classifier import FailureClassifier
from myagentos.failure.stagnation import StagnationDetector


class HealingCoordinator:
    """Coordinates failure classification, limits evaluation, and healing strategies (§14)."""

    def __init__(
        self,
        classifier: FailureClassifier | None = None,
        stagnation_detector: StagnationDetector | None = None,
        limits: JobLimits | None = None,
    ) -> None:
        self.classifier = classifier or FailureClassifier()
        self.stagnation_detector = stagnation_detector or StagnationDetector()
        self.limits = limits or JobLimits()
        self._job_history: dict[str, list[FailureRecord]] = {}

    def evaluate(
        self,
        job_id: str,
        observed: ObservedFailure,
        diff_output: str = "",
        failed_tests: set[str] | None = None,
        cost_usd: float = 0.0,
    ) -> HealingDecision:
        """Evaluates an observed failure and computes the normative healing decision (§14.1)."""
        history = self._job_history.setdefault(job_id, [])
        attempt = len(history) + 1

        # 1. Classify failure deterministically
        code = self.classifier.classify(observed)

        # 2. Record telemetry in StagnationDetector and check (§14.3)
        self.stagnation_detector.record_attempt(
            job_id=job_id,
            attempt_number=attempt,
            failed_tests=failed_tests,
            diagnostic_output=observed.raw_output,
            diff_output=diff_output,
            cost_usd=cost_usd,
        )
        stagnation = self.stagnation_detector.check_stagnation(job_id)

        rule = FAILURE_ACTION_MAP.get(code)
        max_allowed = rule.max_occurrences_per_job if rule else 0

        # Check stagnation first (§14.3)
        if stagnation.stagnated:
            record = FailureRecord(
                code=code,
                action=FailureAction.ESCALATED,
                message=f"Stagnation detected: {stagnation.reason}",
                attempt=attempt,
                max_allowed=max_allowed,
                diagnostics={"raw": observed.raw_output[:500], "reason": stagnation.reason},
            )
            history.append(record)
            return HealingDecision(
                failure_record=record,
                action=FailureAction.ESCALATED,
                can_retry=False,
                fsm_event=EventName.ESCALATED,
                diagnostic_instructions=(
                    f"Job escalated due to lack of progress: {stagnation.reason}"
                ),
                retry_attempt=attempt,
            )

        # 3. Check hard job limits (§14.2)
        if attempt > self.limits.max_attempts:
            record = FailureRecord(
                code=code,
                action=FailureAction.ESCALATED,
                message=f"Hard job attempt limit exceeded ({attempt} > {self.limits.max_attempts})",
                attempt=attempt,
                max_allowed=self.limits.max_attempts,
                diagnostics={"raw": observed.raw_output[:500]},
            )
            history.append(record)
            return HealingDecision(
                failure_record=record,
                action=FailureAction.ESCALATED,
                can_retry=False,
                fsm_event=EventName.ESCALATED,
                diagnostic_instructions="Maximum execution attempts exhausted for this task.",
                retry_attempt=attempt,
            )

        # 4. Check occurrences for this specific failure code
        prior_occurrences = sum(1 for rec in history if rec.code == code)
        if prior_occurrences >= max_allowed:
            # Code-specific limit reached
            action = FailureAction.STOP if max_allowed == 0 else FailureAction.ESCALATED
            record = FailureRecord(
                code=code,
                action=action,
                message=(
                    f"Maximum occurrences for {code.value} reached "
                    f"({prior_occurrences + 1} > {max_allowed})"
                ),
                attempt=attempt,
                max_allowed=max_allowed,
                diagnostics={"raw": observed.raw_output[:500]},
            )
            history.append(record)
            fsm_event = self._map_stop_event(code, action)
            return HealingDecision(
                failure_record=record,
                action=action,
                can_retry=False,
                fsm_event=fsm_event,
                diagnostic_instructions=f"Execution halted: {record.message}",
                retry_attempt=attempt,
            )

        # 5. Apply default rule action
        action = rule.default_action if rule else FailureAction.ESCALATED
        record = FailureRecord(
            code=code,
            action=action,
            message=f"Failure classified as {code.value} -> action {action.value}",
            attempt=attempt,
            max_allowed=max_allowed,
            diagnostics={"raw": observed.raw_output[:500]},
        )
        history.append(record)

        can_retry = action in (
            FailureAction.RETRY,
            FailureAction.CONTEXT_EXPANSION,
            FailureAction.ENV_REPAIR,
        )
        fsm_event = self._map_action_event(action, code)
        instructions = self._generate_diagnostic_instructions(code, observed)

        return HealingDecision(
            failure_record=record,
            action=action,
            can_retry=can_retry,
            fsm_event=fsm_event,
            diagnostic_instructions=instructions,
            retry_attempt=attempt,
        )

    def _map_action_event(self, action: FailureAction, code: FailureCode) -> EventName:
        """Maps a FailureAction to its corresponding FSM event (§14.1)."""
        if action == FailureAction.RETRY:
            return EventName.RETRY_SCHEDULED
        if action == FailureAction.CONTEXT_EXPANSION:
            return EventName.CONTEXT_EXPANDED
        if action == FailureAction.ENV_REPAIR:
            return EventName.ENV_REPAIR_STARTED
        if action == FailureAction.ESCALATED:
            return EventName.ESCALATED
        if action == FailureAction.STOP:
            return self._map_stop_event(code, action)
        return EventName.JOB_FAILED

    def _map_stop_event(self, code: FailureCode, action: FailureAction) -> EventName:
        """Determines the terminal FSM event for STOP/ESCALATED actions (§14.1)."""
        if code == FailureCode.POLICY_VIOLATION:
            return EventName.POLICY_VIOLATION
        if code == FailureCode.MERGE_CONFLICT:
            return EventName.MERGE_CONFLICT
        if code == FailureCode.BUDGET_EXHAUSTED:
            return EventName.BUDGET_PAUSED
        if action == FailureAction.ESCALATED:
            return EventName.ESCALATED
        return EventName.JOB_FAILED

    def _generate_diagnostic_instructions(
        self,
        code: FailureCode,
        observed: ObservedFailure,
    ) -> str:
        """Synthesizes structured feedback for worker retry prompts (§14.1)."""
        diag = observed.raw_output.strip()
        if code == FailureCode.SYNTAX_ERROR:
            return (
                f"[SYNTAX ERROR ENCOUNTERED]\n"
                f"The previous modification contains a syntax error:\n{diag}\n"
                f"Please fix syntax, indentation, and imports carefully."
            )
        if code == FailureCode.TEST_FAILURE:
            return (
                f"[UNIT TEST FAILURE]\n"
                f"Verification failed with the following test diagnostics:\n{diag}\n"
                f"Please inspect failing assertions and correct the implementation logic."
            )
        if code == FailureCode.CONTEXT_MISSING:
            return (
                f"[MISSING CONTEXT / DEFINITIONS]\n"
                f"Missing symbols or internal files encountered:\n{diag}\n"
                f"Expanding context to include missing module definitions."
            )
        if code == FailureCode.ENVIRONMENT_ERROR:
            return (
                f"[ENVIRONMENT ERROR]\n"
                f"Environment or sandbox execution issue:\n{diag}\n"
                f"Initiating sandbox/environment repair."
            )
        if code == FailureCode.REVIEW_REJECTED:
            return (
                f"[CODE REVIEW FEEDBACK]\n"
                f"Independent reviewer rejected changes:\n{diag}\n"
                f"Please revise according to reviewer specifications."
            )
        return f"[EXECUTION FAILURE: {code.value}]\n{diag}"
