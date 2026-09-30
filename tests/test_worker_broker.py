"""Tests for ToolBroker capability enforcement and execution (§10.1, §10.3, §23)."""

from pathlib import Path

from myagentos.core.models.patch import PatchOperation
from myagentos.core.models.risk import RiskLevel
from myagentos.core.models.token import CapabilityToken, NetworkScope, TokenLimits
from myagentos.sandbox.mock import MockSandboxDriver
from myagentos.worker.broker import ToolBroker
from myagentos.worker.models import PatchProposal, ToolCall, ToolStatus


def _create_test_token() -> CapabilityToken:
    return CapabilityToken(
        job_id="job-1",
        worker_id="worker-1",
        risk_level=RiskLevel.LOW,
        read_scope=["src/**"],
        write_scope=["src/**"],
        execute_scope=["pytest", "ruff"],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(
            max_files=5,
            max_diff_lines=100,
            max_steps=10,
        ),
        base_commit="c833c05",
    )


def test_tool_broker_read_permission_enforcement(tmp_path: Path) -> None:
    token = _create_test_token()
    broker = ToolBroker(worktree_path=tmp_path, token=token)

    # Setup files
    src_file = tmp_path / "src" / "app.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("print('hello')", encoding="utf-8")

    secret_file = tmp_path / "secrets.env"
    secret_file.write_text("API_KEY=xyz", encoding="utf-8")

    # 1. Allowed read in src/**
    call_allowed = ToolCall(id="c1", name="read_file", arguments={"path": "src/app.py"})
    res_allowed = broker.execute_tool(call_allowed)
    assert res_allowed.status == ToolStatus.SUCCESS
    assert res_allowed.output == "print('hello')"
    assert res_allowed.trust_tag == "UNTRUSTED"

    # 2. Denied read outside src/**
    call_denied = ToolCall(id="c2", name="read_file", arguments={"path": "secrets.env"})
    res_denied = broker.execute_tool(call_denied)
    assert res_denied.status == ToolStatus.PERMISSION_DENIED
    assert "Read permission denied" in (res_denied.error or "")

    # 3. Path traversal attempt
    call_traversal = ToolCall(id="c3", name="read_file", arguments={"path": "../app.py"})
    res_traversal = broker.execute_tool(call_traversal)
    assert res_traversal.status == ToolStatus.PERMISSION_DENIED


def test_tool_broker_write_and_protected_paths(tmp_path: Path) -> None:
    token = _create_test_token()
    broker = ToolBroker(worktree_path=tmp_path, token=token)

    # 1. Allowed write in src/**
    call_write = ToolCall(
        id="c4",
        name="write_file",
        arguments={"path": "src/new.py", "content": "x = 42"},
    )
    res_write = broker.execute_tool(call_write)
    assert res_write.status == ToolStatus.SUCCESS
    assert (tmp_path / "src" / "new.py").read_text() == "x = 42"

    # 2. Denied write outside write scope (e.g. docs)
    call_denied = ToolCall(
        id="c5",
        name="write_file",
        arguments={"path": "docs/readme.md", "content": "# Readme"},
    )
    res_denied = broker.execute_tool(call_denied)
    assert res_denied.status == ToolStatus.PERMISSION_DENIED

    # 3. Denied write to protected path (§13.2)
    call_protected = ToolCall(
        id="c6",
        name="write_file",
        arguments={"path": "conftest.py", "content": "# hijack"},
    )
    res_protected = broker.execute_tool(call_protected)
    assert res_protected.status == ToolStatus.PERMISSION_DENIED
    assert "Modification of protected path" in (res_protected.error or "")


def test_tool_broker_command_execution(tmp_path: Path) -> None:
    token = _create_test_token()
    sandbox = MockSandboxDriver()
    sandbox.register_mock("pytest", exit_code=0, stdout="1 passed")
    broker = ToolBroker(worktree_path=tmp_path, token=token, sandbox=sandbox)

    # 1. Allowed command in execute scope
    call_cmd = ToolCall(id="c7", name="run_command", arguments={"command": "pytest -q"})
    res_cmd = broker.execute_tool(call_cmd)
    assert res_cmd.status == ToolStatus.SUCCESS
    assert "1 passed" in res_cmd.output

    # 2. Denied command (not in execute scope)
    call_unauthorized = ToolCall(
        id="c8",
        name="run_command",
        arguments={"command": "curl http://malicious.com"},
    )
    res_unauth = broker.execute_tool(call_unauthorized)
    assert res_unauth.status == ToolStatus.PERMISSION_DENIED
    assert "Execution permission denied" in (res_unauth.error or "")


def test_tool_broker_propose_patch(tmp_path: Path) -> None:
    token = _create_test_token()
    broker = ToolBroker(worktree_path=tmp_path, token=token)

    f_src = tmp_path / "src" / "calc.py"
    f_src.parent.mkdir(parents=True)
    f_src.write_text("def add(a, b): return a - b\n")

    proposal_dict = {
        "description": "Fix subtraction in add function",
        "files": [
            {
                "path": "src/calc.py",
                "operation": "MODIFY",
                "content": "def add(a, b): return a + b\n",
            }
        ],
    }
    call_patch = ToolCall(id="c9", name="propose_patch", arguments=proposal_dict)
    res_patch = broker.execute_tool(call_patch)
    assert res_patch.status == ToolStatus.SUCCESS

    # Build and verify PatchSet
    proposal = PatchProposal.model_validate(proposal_dict)
    patch_set = broker.build_patch_set_from_proposal(job_id="job-1", proposal=proposal)
    assert len(patch_set.files) == 1
    assert patch_set.files[0].operation == PatchOperation.MODIFY
    assert patch_set.files[0].sha256_before != ""
    assert patch_set.files[0].sha256_after != ""
