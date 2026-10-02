"""End-to-end integration tests for PipelineOrchestrator and CLI run (§8)."""

import json
from pathlib import Path
from typing import Any

import pytest

from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator


class ScriptedE2EAdapter(ProviderAdapter):
    """Feeds sequential responses to Planner and Worker across the E2E lifecycle."""

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
        return LLMResponse(content=resp, model_id=model_id, input_tokens=30, output_tokens=50)


def test_pipeline_e2e_direct_worker_code_fast_path(tmp_path: Path) -> None:
    # 1. Setup repository
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    calc_file = src_dir / "calc.py"
    calc_file.write_text("def add(a, b): return a - b\n")

    # Worker response proposing patch
    worker_resp = json.dumps(
        {
            "thought": "Fixing subtraction bug in add function",
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

    adapter = ScriptedE2EAdapter([worker_resp])
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=False,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)

    result = orchestrator.run("/direct fix add function in src/calc.py")

    assert result.success is True
    assert result.final_state == JobState.COMPLETE
    assert result.intent == "DIRECT_WORKER_CODE"
    assert result.patch_set is not None
    assert result.patch_set.total_files == 1
    assert result.hash_chain_intact is True
    assert result.audit_events_count >= 10

    # Verify file was actually modified in repo root
    assert calc_file.read_text() == "def add(a, b): return a + b\n"


def test_pipeline_e2e_planned_code_lifecycle(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    api_file = src_dir / "api.py"
    api_file.write_text("def get_status(): return 'offline'\n")

    # 1. Planner response
    planner_resp = json.dumps(
        {
            "files_to_modify": ["src/api.py"],
            "files_to_create": [],
            "files_to_delete": [],
            "altered_interfaces": ["def get_status() -> str"],
            "test_specs": ["test_get_status_online"],
            "preliminary_risk": "MEDIUM",
            "risk_reasons": ["Core API status change"],
            "permissions_requested": {
                "read": ["src/api.py"],
                "write": ["src/api.py"],
                "execute": ["pytest"],
            },
            "impact_summary": "Updates health status return",
            "rationale": "Change offline to online",
        }
    )

    # 2. Worker response
    worker_resp = json.dumps(
        {
            "thought": "Updating status to online",
            "propose_patch": {
                "description": "Switch offline to online",
                "files": [
                    {
                        "path": "src/api.py",
                        "operation": "MODIFY",
                        "content": "def get_status(): return 'online'\n",
                    }
                ],
            },
        }
    )

    adapter = ScriptedE2EAdapter([planner_resp, worker_resp])
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=False,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)

    result = orchestrator.run("Refactor health endpoint to return online in src/api.py")

    assert result.success is True
    assert result.final_state == JobState.COMPLETE
    assert result.intent == "PLANNED_CODE"
    assert result.plan is not None
    assert result.plan.version == 1
    assert result.approval is not None
    assert result.patch_set is not None
    assert result.hash_chain_intact is True

    # Verify modification
    assert api_file.read_text() == "def get_status(): return 'online'\n"


def test_pipeline_e2e_plan_rejection(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    target = src_dir / "user.py"
    target.write_text("class User: pass\n")

    planner_resp = json.dumps(
        {
            "files_to_modify": ["src/user.py"],
            "preliminary_risk": "HIGH",
            "permissions_requested": {"read": ["src/user.py"], "write": ["src/user.py"]},
        }
    )

    adapter = ScriptedE2EAdapter([planner_resp])
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    # Approval callback returns False (rejects plan)
    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=False,
        approval_callback=lambda plan_id, plan: False,
        use_worktree=False,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)

    result = orchestrator.run("Change user model in src/user.py")

    assert result.success is False
    assert result.final_state == JobState.CANCELLED
    assert "rejected" in result.summary.lower()


def test_cli_cmd_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from myagentos.cli import cmd_run
    from myagentos.gateway.mock_adapter import MockProviderAdapter

    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    target = src_dir / "msg.py"
    target.write_text("MESSAGE = 'old'\n")

    # Scripted output for worker
    worker_resp = json.dumps(
        {
            "thought": "Updating message",
            "propose_patch": {
                "description": "Set message to new",
                "files": [
                    {
                        "path": "src/msg.py",
                        "operation": "MODIFY",
                        "content": "MESSAGE = 'new'\n",
                    }
                ],
            },
        }
    )

    mock_adapter = MockProviderAdapter()
    mock_adapter.preset_responses["fix message"] = worker_resp

    orig_init = ModelGateway.__init__

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        orig_init(self, *args, **kwargs)
        self.register_adapter("mock", mock_adapter)

    monkeypatch.setattr(ModelGateway, "__init__", patched_init)

    # Invoke cmd_run
    cmd_run(
        prompt="/direct fix message in src/msg.py",
        repo_path=str(tmp_path),
        auto_approve=True,
        model_id="mock",
    )

    # Verify disk state
    assert target.read_text() == "MESSAGE = 'new'\n"
