"""Tests for the bounded Worker loop (§10.2, §10.3)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from myagentos.core.models.event import EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.models.token import CapabilityToken, NetworkScope, TokenLimits
from myagentos.core.store.event_store import EventStore
from myagentos.gateway import MockProviderAdapter, ModelGateway
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.worker.broker import ToolBroker
from myagentos.worker.loop import WorkerLoop


def _create_token(max_steps: int = 5, max_seconds: int = 30) -> CapabilityToken:
    return CapabilityToken(
        job_id="job-loop-1",
        worker_id="worker-1",
        risk_level=RiskLevel.LOW,
        read_scope=["src/**"],
        write_scope=["src/**"],
        execute_scope=["pytest"],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(
            max_files=5,
            max_diff_lines=100,
            max_steps=max_steps,
        ),
        base_commit="c833c05",
        expires_at=datetime.now(UTC) + timedelta(seconds=max_seconds),
    )


class ScriptedAdapter(ProviderAdapter):
    """Adapter that returns sequential scripted responses for testing multi-turn loops."""

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
        return LLMResponse(content=resp, model_id=model_id, input_tokens=10, output_tokens=10)


def test_worker_loop_multi_step_flow(tmp_path: Path) -> None:
    """Verifies multi-step loop where Worker reads file then proposes patch."""
    token = _create_token(max_steps=5)
    broker = ToolBroker(worktree_path=tmp_path, token=token)
    store = EventStore(root_dir=tmp_path / ".events")

    # Target file
    src_file = tmp_path / "src" / "calc.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("def add(a, b): return a - b\n")

    # Scripted 2-turn dialogue
    turn1 = json.dumps(
        {
            "thought": "I need to inspect calc.py",
            "tool_call": {
                "name": "read_file",
                "arguments": {"path": "src/calc.py"},
            },
        }
    )
    turn2 = json.dumps(
        {
            "thought": "Found bug, proposing patch",
            "propose_patch": {
                "description": "Fix add implementation",
                "files": [
                    {
                        "path": "src/calc.py",
                        "operation": "MODIFY",
                        "content": "def add(a, b): return a + b\n",
                    }
                ],
            },
        }
    )

    gateway = ModelGateway()
    gateway.register_adapter("mock", ScriptedAdapter([turn1, turn2]))

    loop = WorkerLoop(
        gateway=gateway,
        broker=broker,
        job_id="job-loop-1",
        token=token,
        event_store=store,
    )

    result = loop.run("Fix the add function in src/calc.py")

    assert result.success is True
    assert result.stop_reason == "PROPOSE_PATCH"
    assert result.patch_set is not None
    assert result.total_steps == 2

    # Verify file was actually modified in worktree
    assert src_file.read_text() == "def add(a, b): return a + b\n"

    # Verify event audit trail
    events = store.load_events("job-loop-1")
    event_names = [e.event_name for e in events]
    assert EventName.WORKER_STARTED in event_names
    assert EventName.TOOL_CALL in event_names
    assert EventName.PATCH_CREATED in event_names


def test_worker_loop_max_steps_enforcement(tmp_path: Path) -> None:
    """Verifies that the loop strictly respects max_steps limit (§10.3)."""
    token = _create_token(max_steps=2)
    broker = ToolBroker(worktree_path=tmp_path, token=token)

    # Infinite tool loop attempt
    loop_response = json.dumps(
        {
            "thought": "Reading repeatedly",
            "tool_call": {
                "name": "read_file",
                "arguments": {"path": "src/none.py"},
            },
        }
    )
    gateway = ModelGateway()
    mock_adapter = MockProviderAdapter()
    mock_adapter.set_response("", loop_response)
    gateway.register_adapter("mock", mock_adapter)

    loop = WorkerLoop(
        gateway=gateway,
        broker=broker,
        job_id="job-limit-1",
        token=token,
    )

    result = loop.run("Task that loops")
    assert result.success is False
    assert result.stop_reason == "MAX_STEPS"
    assert result.total_steps == 2


def test_worker_loop_timeout_enforcement(tmp_path: Path) -> None:
    """Verifies that expired tokens immediately trigger TIMEOUT (§10.3)."""
    # Create token already expired in the past
    token = CapabilityToken(
        job_id="job-timeout-1",
        worker_id="worker-1",
        risk_level=RiskLevel.LOW,
        read_scope=["src/**"],
        write_scope=["src/**"],
        execute_scope=[],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(max_steps=5),
        base_commit="c833c05",
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    broker = ToolBroker(worktree_path=tmp_path, token=token)

    gateway = ModelGateway()
    mock_adapter = MockProviderAdapter()
    gateway.register_adapter("mock", mock_adapter)

    loop = WorkerLoop(
        gateway=gateway,
        broker=broker,
        job_id="job-timeout-1",
        token=token,
    )

    result = loop.run("Task on expired token")
    assert result.success is False
    assert result.stop_reason == "TIMEOUT"
