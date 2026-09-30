"""End-to-end integration tests for self-healing and stagnation in PipelineOrchestrator (§14)."""

import json
from pathlib import Path
from typing import Any

import pytest

from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator
from myagentos.sandbox.base import ExecutionLimits, ExecutionResult, SandboxDriver


class ScriptedSequenceAdapter(ProviderAdapter):
    """Yields a sequence of scripted LLM responses across worker loop retries."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.index = 0

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type | None = None,
    ) -> LLMResponse:
        if self.index < len(self.responses):
            resp = self.responses[self.index]
            self.index += 1
        else:
            resp = self.responses[-1]
        return LLMResponse(content=resp, model_id=model_id, input_tokens=40, output_tokens=80)


class FlakyVerificationSandbox(SandboxDriver):
    """Sandbox driver where test commands fail on the first call and succeed on the second."""

    def __init__(self) -> None:
        self.call_count = 0

    def run_command(
        self,
        command: str,
        worktree_path: Path,
        limits: ExecutionLimits | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> ExecutionResult:
        self.call_count += 1
        if self.call_count == 1:
            return ExecutionResult(
                exit_code=1,
                stdout="running tests...\n",
                stderr=(
                    "FAILED test_app.py::test_fn - AssertionError: assert 100 == 200\n"
                    "=== 1 failed ==="
                ),
                duration_seconds=0.1,
            )
        return ExecutionResult(
            exit_code=0,
            stdout="running tests...\n=== 1 passed ===",
            stderr="",
            duration_seconds=0.1,
        )

    def close(self) -> None:
        pass


def test_pipeline_self_healing_retry_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that when verification fails, the pipeline classifies and heals (§14)."""
    # 1. Setup repository
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    target_file = src_dir / "calc.py"
    target_file.write_text("VALUE = 0\n")

    # Worker response 1 (causes verification failure)
    resp_1 = json.dumps(
        {
            "thought": "First attempt with partial fix",
            "propose_patch": {
                "description": "Set VALUE to 100",
                "files": [
                    {
                        "path": "src/calc.py",
                        "operation": "MODIFY",
                        "content": "VALUE = 100\n",
                    }
                ],
            },
        }
    )

    # Worker response 2 (fixes the issue after receiving retry diagnostics)
    resp_2 = json.dumps(
        {
            "thought": "Fixing according to test failure diagnostics",
            "propose_patch": {
                "description": "Set VALUE to 200",
                "files": [
                    {
                        "path": "src/calc.py",
                        "operation": "MODIFY",
                        "content": "VALUE = 200\n",
                    }
                ],
            },
        }
    )

    scripted_adapter = ScriptedSequenceAdapter([resp_1, resp_2])
    gateway = ModelGateway()
    gateway.register_adapter("mock", scripted_adapter)

    sandbox = FlakyVerificationSandbox()

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(
        config=config,
        gateway=gateway,
        sandbox_driver=sandbox,
    )

    # Configure verification guard to execute simulated project tests
    orig_verify = orchestrator.verification_guard.verify

    def patched_verify(*args: Any, **kwargs: Any) -> Any:
        kwargs["project_test_cmd"] = "pytest"
        return orig_verify(*args, **kwargs)

    monkeypatch.setattr(orchestrator.verification_guard, "verify", patched_verify)

    result = orchestrator.run("/direct fix calculation in src/calc.py")

    assert result.success is True
    assert result.final_state == JobState.COMPLETE
    assert result.hash_chain_intact is True
    assert target_file.read_text() == "VALUE = 200\n"

    # Verify audit events include TEST_FAILED, FAILURE_CLASSIFIED, and RETRY_SCHEDULED
    events = orchestrator.event_store.load_events(result.job_id)
    event_names = [e.event_name for e in events]
    assert "TEST_FAILED" in event_names
    assert "FAILURE_CLASSIFIED" in event_names
    assert "RETRY_SCHEDULED" in event_names
    assert "MERGE_COMPLETED" in event_names
    assert "JOB_COMPLETED" in event_names


def test_pipeline_stagnation_detection_escalates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that identical failing patches across attempts trigger stagnation (§14.3)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    target_file = src_dir / "stuck.py"
    target_file.write_text("X = 1\n")

    # Worker repeatedly returns the identical patch
    identical_resp = json.dumps(
        {
            "thought": "Applying identical patch",
            "propose_patch": {
                "description": "Identical patch",
                "files": [
                    {
                        "path": "src/stuck.py",
                        "operation": "MODIFY",
                        "content": "X = 2\n",
                    }
                ],
            },
        }
    )

    scripted_adapter = ScriptedSequenceAdapter([identical_resp, identical_resp, identical_resp])
    gateway = ModelGateway()
    gateway.register_adapter("mock", scripted_adapter)

    class AlwaysFailingSandbox(SandboxDriver):
        def run_command(
            self,
            command: str,
            worktree_path: Path,
            limits: ExecutionLimits | None = None,
            env_vars: dict[str, str] | None = None,
        ) -> ExecutionResult:
            return ExecutionResult(
                exit_code=1,
                stdout="",
                stderr="FAILED test_stuck.py - AssertionError: X != 999",
                duration_seconds=0.1,
            )

        def close(self) -> None:
            pass

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(
        config=config,
        gateway=gateway,
        sandbox_driver=AlwaysFailingSandbox(),
    )

    orig_verify = orchestrator.verification_guard.verify

    def patched_verify(*args: Any, **kwargs: Any) -> Any:
        kwargs["project_test_cmd"] = "pytest"
        return orig_verify(*args, **kwargs)

    monkeypatch.setattr(orchestrator.verification_guard, "verify", patched_verify)

    result = orchestrator.run("/direct fix X in src/stuck.py")

    assert result.success is False
    assert result.final_state == JobState.ESCALATED
    assert "Stagnation detected" in result.summary

    events = orchestrator.event_store.load_events(result.job_id)
    event_names = [e.event_name for e in events]
    assert "ESCALATED" in event_names
