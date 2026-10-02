"""Comprehensive regression test suite for security audit findings AGF-001 through AGF-007.

Adheres strictly to the regression matrix defined in Section 14 of
docs/new_features/agentic-os-audit-fix-global.md.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myagentos.core.errors import (
    PathEscapeError,
    SandboxUnavailableError,
)
from myagentos.core.models.failure import FailureCode
from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.risk import RiskLevel
from myagentos.core.models.token import CapabilityToken, TokenLimits
from myagentos.core.paths import (
    safe_walk,
    validate_safe_path,
)
from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.gateway.mock_adapter import MockProviderAdapter
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator
from myagentos.reviewer.approval import DiffApprovalManager, compute_canonical_patch_digest
from myagentos.sandbox.base import ExecutionLimits
from myagentos.sandbox.mock import MockSandboxDriver
from myagentos.verification.guard import VerificationGuard
from myagentos.verification.profile import VerificationProfile
from myagentos.worker.broker import ToolBroker
from myagentos.worker.models import FileEditProposal, PatchProposal, ToolStatus
from myagentos.worktree.patch_applier import apply_patch_set, calculate_file_sha256


def _create_token(
    read_scope: list[str] | None = None,
    write_scope: list[str] | None = None,
    execute_scope: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> CapabilityToken:
    return CapabilityToken(
        job_id="job-test",
        worker_id="worker-1",
        risk_level=RiskLevel.LOW,
        base_commit="c0ffee",
        read_scope=read_scope or ["**/*"],
        write_scope=write_scope or ["src/**/*"],
        execute_scope=execute_scope or ["pytest", "echo"],
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        limits=TokenLimits(max_files=10),
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _ScriptedAdapter(ProviderAdapter):
    """Feeds deterministic sequential responses (planner first, then worker)."""

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
        resp = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return LLMResponse(content=resp, model_id=model_id, input_tokens=30, output_tokens=50)


def _gateway_with(*responses: str) -> ModelGateway:
    gateway = ModelGateway()
    gateway.register_adapter("mock", _ScriptedAdapter(list(responses)))
    return gateway


# ---------------------------------------------------------------------------
# Case 1 & 2: Traversal, Scope, and Absolute Path Rejection (AGF-001, AGF-003)
# ---------------------------------------------------------------------------


def test_proposal_out_of_write_scope_rejected_before_disk_changes(tmp_path: Path) -> None:
    """Proposal targeting file outside write_scope is rejected without any disk writes."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "src").mkdir()
    (worktree / "src" / "app.py").write_text("initial = True\n")
    (worktree / "etc").mkdir()
    (worktree / "etc" / "config.json").write_text('{"safe": true}\n')

    # Standard recursive glob "src/**/*" covers direct children (src/app.py) as well as subdirs
    token = _create_token(write_scope=["src/**/*"])
    broker = ToolBroker(worktree_path=worktree, token=token)

    # Proposal includes one allowed file and one out-of-scope file
    proposal = PatchProposal(
        description="Malicious batch",
        files=[
            FileEditProposal(
                path="src/app.py", operation=PatchOperation.MODIFY, content="initial = False\n"
            ),
            FileEditProposal(
                path="etc/config.json",
                operation=PatchOperation.MODIFY,
                content='{"safe": false, "pwned": true}\n',
            ),
        ],
    )

    valid, err = broker.validate_proposal(proposal)
    assert valid is False
    assert err is not None
    assert "outside write scope" in err
    # The rejection must be caused by the external file, not by the in-scope one
    assert "etc/config.json" in err
    assert "src/app.py" not in err

    # Ensure no file in the worktree was touched
    assert (worktree / "src" / "app.py").read_text() == "initial = True\n"
    assert (worktree / "etc" / "config.json").read_text() == '{"safe": true}\n'


def test_recursive_glob_pattern_matches_direct_and_nested_descendants() -> None:
    """Standard recursive glob 'src/**/*' authorizes both direct children and deep files."""
    token = _create_token(write_scope=["src/**/*"], read_scope=["src/**/*"])
    assert token.is_write_allowed("src/app.py") is True
    assert token.is_write_allowed("src/sub/deep/module.py") is True
    assert token.is_write_allowed("etc/config.json") is False
    assert token.is_write_allowed("src_fake/app.py") is False

    assert token.is_read_allowed("src/app.py") is True
    assert token.is_read_allowed("src/sub/deep/module.py") is True
    assert token.is_read_allowed("etc/config.json") is False


def test_traversal_and_absolute_path_patch_rejected(tmp_path: Path) -> None:
    """Path traversal (../outside) and absolute paths are rejected with no external effects."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside_file = tmp_path / "victim.txt"
    outside_file.write_text("protected content\n")

    token = _create_token(write_scope=["**/*"])
    broker = ToolBroker(worktree_path=worktree, token=token)

    # 1. Traversal in proposal
    proposal_traversal = PatchProposal(
        description="Traversal escape",
        files=[
            FileEditProposal(
                path="../victim.txt",
                operation=PatchOperation.MODIFY,
                content="overwritten\n",
            )
        ],
    )
    valid, err = broker.validate_proposal(proposal_traversal)
    assert valid is False
    assert err is not None

    # 2. Direct validation
    with pytest.raises(PathEscapeError):
        validate_safe_path(worktree, "../victim.txt")

    with pytest.raises(PathEscapeError):
        validate_safe_path(worktree, "/etc/passwd")

    with pytest.raises(PathEscapeError):
        validate_safe_path(worktree, "subdir/../../victim.txt")

    # 3. Patch applier rejects traversal
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="c1",
        files=[
            FilePatch(
                path="../victim.txt",
                operation=PatchOperation.MODIFY,
                patch="hacked\n",
                sha256_before="0" * 64,
                sha256_after="1" * 64,
            )
        ],
    )
    ok, app_err = apply_patch_set(worktree, patch_set)
    assert ok is False
    assert outside_file.read_text() == "protected content\n"


# ---------------------------------------------------------------------------
# Case 3 & 4: Rename and Diff Target Path Validation (AGF-001)
# ---------------------------------------------------------------------------


def test_rename_unauthorized_source_rejected(tmp_path: Path) -> None:
    """Rename operation where old_path is outside scope or missing is rejected."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "src").mkdir()
    (worktree / "docs").mkdir()
    (worktree / "docs" / "secret.txt").write_text("secret\n")

    token = _create_token(write_scope=["src/**/*"])
    broker = ToolBroker(worktree_path=worktree, token=token)

    # Rename with source outside write scope (destination src/renamed.txt IS in scope)
    proposal = PatchProposal(
        description="Rename source escape",
        files=[
            FileEditProposal(
                path="src/renamed.txt",
                operation=PatchOperation.RENAME,
                old_path="docs/secret.txt",
                content="",
            )
        ],
    )
    valid, err = broker.validate_proposal(proposal)
    assert valid is False
    assert err is not None
    assert "Rename source" in err
    assert "outside write scope" in err

    # Rename with non-existent source
    proposal_nonexist = PatchProposal(
        description="Rename nonexistent source",
        files=[
            FileEditProposal(
                path="src/renamed.txt",
                operation=PatchOperation.RENAME,
                old_path="src/missing.txt",
                content="",
            )
        ],
    )
    valid2, err2 = broker.validate_proposal(proposal_nonexist)
    assert valid2 is False
    assert err2 is not None
    assert "Invalid rename source" in err2


def test_diff_headers_unauthorized_destination_rejected(tmp_path: Path) -> None:
    """Unified diff with headers targeting a different file is rejected before application."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "app.py").write_text("original\n")
    (worktree / "secret.py").write_text("secret\n")

    token = _create_token(write_scope=["app.py"])
    broker = ToolBroker(worktree_path=worktree, token=token)

    diff_content = (
        "--- a/app.py\n"
        "+++ b/secret.py\n"
        "@@ -1 +1 @@\n"
        "-secret\n"
        "+pwned\n"
    )

    proposal = PatchProposal(
        description="Diff spoofing",
        files=[
            FileEditProposal(
                path="app.py",
                operation=PatchOperation.MODIFY,
                content=diff_content,
            )
        ],
    )
    valid, err = broker.validate_proposal(proposal)
    assert valid is False
    assert err is not None
    assert "Diff headers" in err

    # Applier also independently rejects diff target mismatch. The before-hash must be the
    # real one, otherwise the applier would reject on hash mismatch before inspecting headers.
    real_before = calculate_file_sha256(worktree / "app.py")
    patch_set = PatchSet(
        job_id="job-spoof",
        base_commit="c1",
        files=[
            FilePatch(
                path="app.py",
                operation=PatchOperation.MODIFY,
                patch=diff_content,
                sha256_before=real_before,
                sha256_after="1" * 64,
            )
        ],
    )
    app_ok, app_err = apply_patch_set(worktree, patch_set)
    assert app_ok is False
    assert "header targeting" in str(app_err)
    assert (worktree / "secret.py").read_text() == "secret\n"


# ---------------------------------------------------------------------------
# Case 5: Symlink File and Directory Traversal Rejection (AGF-003)
# ---------------------------------------------------------------------------


def test_symlink_file_and_directory_access_denied(tmp_path: Path) -> None:
    """Broker tools refuse to read, write, or search through symlinks pointing outside."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    secret_dir = tmp_path / "outside_vault"
    secret_dir.mkdir()
    secret_file = secret_dir / "keys.txt"
    secret_file.write_text("SECRET_API_KEY_12345\n")

    # Create symlink file inside worktree pointing to secret file
    link_file = worktree / "link_to_keys.txt"
    try:
        link_file.symlink_to(secret_file)
    except OSError:
        pytest.skip("Symlinks not supported on this filesystem")

    # Create symlink directory inside worktree pointing to secret directory
    link_dir = worktree / "link_to_vault"
    link_dir.symlink_to(secret_dir)

    # "*" (not "**/*") so root-level files are IN scope: denial must come from the symlink check
    token = _create_token(read_scope=["*"], write_scope=["*"])
    broker = ToolBroker(worktree_path=worktree, token=token)

    # 1. tool_read_file on symlink file -> PERMISSION_DENIED
    res_read = broker.tool_read_file("c1", "link_to_keys.txt")
    assert res_read.status == ToolStatus.PERMISSION_DENIED
    assert "containment" in (res_read.error or "").lower()

    # 2. tool_read_file through symlink directory -> PERMISSION_DENIED
    res_read_dir = broker.tool_read_file("c2", "link_to_vault/keys.txt")
    assert res_read_dir.status == ToolStatus.PERMISSION_DENIED
    assert "containment" in (res_read_dir.error or "").lower()

    # 3. tool_write_file on symlink file -> PERMISSION_DENIED
    res_write = broker.tool_write_file("c3", "link_to_keys.txt", "overwritten")
    assert res_write.status == ToolStatus.PERMISSION_DENIED
    assert secret_file.read_text() == "SECRET_API_KEY_12345\n"

    # 4. tool_search_symbols does not traverse into symlink directory
    res_search = broker.tool_search_symbols("c4", "SECRET_API_KEY")
    assert "SECRET_API_KEY" not in res_search.output

    # 5. safe_walk ignores symlinks completely
    # safe_walk yields (absolute_path, relative_path) tuples; a regular file proves the walk
    # is not vacuous.
    (worktree / "regular.txt").write_text("ok\n")
    walked = {rel for _, rel in safe_walk(worktree)}
    assert "regular.txt" in walked
    assert "link_to_keys.txt" not in walked
    assert not any(rel.startswith("link_to_vault") for rel in walked)
    assert not any("keys.txt" in rel for rel in walked)


# ---------------------------------------------------------------------------
# Case 6 & 8: Structured Command Execution & Process Group Termination (AGF-002)
# ---------------------------------------------------------------------------


def test_chained_command_rejected_by_broker_and_token() -> None:
    """Shell chaining operators (;, &&, ||, |, &, newline, backticks) are rejected."""
    token = _create_token(execute_scope=["pytest", "ls"])

    # Token-level check
    assert token.is_execute_allowed("pytest") is True
    assert token.is_execute_allowed("pytest; rm -rf /") is False
    assert token.is_execute_allowed("pytest && cat /etc/passwd") is False
    assert token.is_execute_allowed("pytest || echo pwn") is False
    assert token.is_execute_allowed("ls | grep secret") is False
    assert token.is_execute_allowed("pytest & bg_job") is False
    assert token.is_execute_allowed("pytest\nrm -rf /") is False
    assert token.is_execute_allowed("`id`") is False
    assert token.is_execute_allowed("$(whoami)") is False
    assert token.is_execute_allowed("ls > out.txt") is False

    # Broker tool check
    broker = ToolBroker(worktree_path=Path("."), token=token)
    res = broker.tool_run_command("c1", "pytest && rm -rf /")
    assert res.status == ToolStatus.PERMISSION_DENIED
    assert "chaining" in (res.error or "").lower()


def test_subprocess_timeout_process_group_sigkill(tmp_path: Path) -> None:
    """MockSandboxDriver terminates command and process tree cleanly on timeout."""
    driver = MockSandboxDriver(use_real_subprocess=True)

    # Command that would run 10 seconds, but timeout is 1 second
    res = driver.run_command(
        command=["python3", "-c", "import time; time.sleep(10)"],
        worktree_path=tmp_path,
        limits=ExecutionLimits(timeout_seconds=1),
    )
    assert res.timed_out is True
    assert "timed out" in res.stderr.lower()
    assert res.exit_code in (-1, 124)


# ---------------------------------------------------------------------------
# Case 7: Sandbox Availability Rejection (AGF-002)
# ---------------------------------------------------------------------------


def test_missing_sandbox_blocks_non_mock_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-mock pipeline without Docker raises SandboxUnavailableError and halts."""
    from myagentos.sandbox.docker import DockerSandboxDriver

    monkeypatch.setattr(DockerSandboxDriver, "is_available", classmethod(lambda cls: False))

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="gpt-4o",  # Non-mock model requires real sandbox
        auto_approve=True,
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", MockProviderAdapter())

    with pytest.raises(SandboxUnavailableError) as exc_info:
        PipelineOrchestrator(config=config, gateway=gateway, sandbox_driver=None)

    assert "Isolated sandbox driver (Docker) is not available" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Case 9 & 10: Explicit Approvals & Skill Risk Elevation (AGF-005)
# ---------------------------------------------------------------------------


def test_missing_approval_callback_halts_pipeline(tmp_path: Path) -> None:
    """When auto_approve=False and no callback provided, pipeline halts safely."""
    # A HIGH-risk plan forces WAIT_PLAN_APPROVAL; LOW-risk plans legitimately skip approval.
    planner_resp = json.dumps(
        {
            "files_to_create": ["src/dummy_test.py"],
            "preliminary_risk": "HIGH",
            "permissions_requested": {
                "read": ["src/dummy_test.py"],
                "write": ["src/dummy_test.py"],
            },
        }
    )
    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=False,  # Human approval mandatory
        approval_callback=None,  # No interactive callback provided
        use_worktree=False,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=_gateway_with(planner_resp))
    result = orchestrator.run("create a dummy test file")

    assert result.success is False
    assert result.final_state == JobState.CANCELLED
    assert result.patch_set is None
    assert "missing callback" in result.summary
    assert not (tmp_path / "src" / "dummy_test.py").exists()


def test_skill_elevated_risk_requires_plan_approval_before_worktree(tmp_path: Path) -> None:
    """Skill with min_risk=HIGH elevates LOW task to HIGH, requiring approval before worktree."""
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "crypto"
    skill_dir.mkdir(parents=True)
    skill_content = (
        "---\nname: crypto\ndescription: Cryptography skill\nversion: 1.0.0\n"
        "min_risk_level: HIGH\ntags: [security]\ntriggers: [crypto, cipher]\nsource: project\n"
        "---\n\nRules"
    )
    (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=False,
        skills_dir=skills_dir,
    )
    gateway = ModelGateway()
    gateway.register_adapter("mock", MockProviderAdapter())

    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)
    result = orchestrator.run("implement cipher encryption in src/cipher.py")

    assert result.success is False
    assert result.final_state in (JobState.WAIT_PLAN_APPROVAL, JobState.CANCELLED)


# ---------------------------------------------------------------------------
# Case 11: Semantic Diff Digest and Versioning (AGF-007)
# ---------------------------------------------------------------------------


def test_modify_to_empty_vs_delete_produce_distinct_digests() -> None:
    """MODIFY to empty content vs DELETE must produce distinct SHA-256 canonical digests."""
    # Identical hashes on both sets: ONLY the operation differs, so the digest must encode it.
    h_before, h_after = _sha256("old\n"), _sha256("")
    patch_modify_empty = PatchSet(
        job_id="job-1",
        base_commit="commit-1",
        files=[
            FilePatch(
                path="app.py",
                operation=PatchOperation.MODIFY,
                patch="",
                sha256_before=h_before,
                sha256_after=h_after,
            )
        ],
    )
    patch_delete = PatchSet(
        job_id="job-1",
        base_commit="commit-1",
        files=[
            FilePatch(
                path="app.py",
                operation=PatchOperation.DELETE,
                patch="",
                sha256_before=h_before,
                sha256_after=h_after,
            )
        ],
    )

    digest_modify = compute_canonical_patch_digest(patch_modify_empty, schema_version=2)
    digest_delete = compute_canonical_patch_digest(patch_delete, schema_version=2)

    assert digest_modify != digest_delete
    assert digest_modify.startswith("v2:")
    assert digest_delete.startswith("v2:")


def test_approval_manager_invalidates_tampered_patch_and_obsolete_schema() -> None:
    """ApprovalManager invalidates approval if patch content changes or schema is obsolete."""
    manager = DiffApprovalManager()
    patch_orig = PatchSet(
        job_id="job-1",
        base_commit="c1",
        files=[
            FilePatch(
                path="main.py",
                operation=PatchOperation.CREATE,
                patch="print('hello')\n",
                sha256_before="",
                sha256_after=_sha256("print('hello')\n"),
            )
        ],
    )

    approval = manager.create_approval("job-1", patch_orig, schema_version=2)
    ok, err = manager.validate_approval(approval, patch_orig)
    assert ok is True
    assert err is None

    # Tampered patch: same path, different patch content
    patch_tampered = PatchSet(
        job_id="job-1",
        base_commit="c1",
        files=[
            FilePatch(
                path="main.py",
                operation=PatchOperation.CREATE,
                patch="print('pwned')\n",
                sha256_before="",
                # Same hashes as the approved patch: only the patch text differs, so the
                # digest must cover the patch content itself.
                sha256_after=_sha256("print('hello')\n"),
            )
        ],
    )
    ok_tamp, err_tamp = manager.validate_approval(approval, patch_tampered)
    assert ok_tamp is False
    assert "hash mismatch" in str(err_tamp).lower()

    # Obsolete schema (< 2)
    approval_obsolete = approval.model_copy(update={"schema_version": 1})
    ok_obs, err_obs = manager.validate_approval(approval_obsolete, patch_orig)
    assert ok_obs is False
    assert "obsolete schema version" in str(err_obs)


# ---------------------------------------------------------------------------
# Case 12 & 13: Effective Verification & Zero-Stage Rejection (AGF-004)
# ---------------------------------------------------------------------------


def test_invalid_python_syntax_fails_verification(tmp_path: Path) -> None:
    """VerificationGuard detects invalid Python syntax without external tools."""
    guard = VerificationGuard(sandbox_driver=MockSandboxDriver())
    bad_code_dir = tmp_path / "src"
    bad_code_dir.mkdir(parents=True)
    (bad_code_dir / "broken.py").write_text("def broken(:\n    pass\n")

    res = guard.verify(worktree_path=tmp_path, base_commit="c1")
    assert res.passed is False
    assert res.failure_code == FailureCode.SYNTAX_ERROR
    assert "SyntaxError" in res.diagnostics or "invalid syntax" in res.diagnostics


def test_zero_stage_verification_rejected_for_code(tmp_path: Path) -> None:
    """Code change where 0 verification stages run is rejected with CONFIG_ERROR."""
    guard = VerificationGuard(sandbox_driver=MockSandboxDriver())
    # Directory with non-Python code and no compile, lint, or test commands configured
    doc_dir = tmp_path / "docs"
    doc_dir.mkdir(parents=True)
    (doc_dir / "guide.md").write_text("# Guide\n")

    # is_non_code=False forces verification to require at least one stage
    profile = VerificationProfile(is_non_code=False)
    res = guard.verify(
        worktree_path=tmp_path,
        base_commit="c1",
        compile_cmd=None,
        lint_cmd=None,
        project_test_cmd=None,
        profile=profile,
    )
    assert res.passed is False
    assert res.failure_code == FailureCode.CONFIG_ERROR
    assert "Zero verification stages" in res.diagnostics


# ---------------------------------------------------------------------------
# Case 14, 15, 16: Transactional Integrity, Rollback & Conflicts (AGF-006)
# ---------------------------------------------------------------------------


def test_batch_patch_partial_failure_atomic_rollback(tmp_path: Path) -> None:
    """When a patch in a batch fails, previous patches in that batch are rolled back cleanly."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "file_a.py").write_text("ORIGINAL A\n")
    (worktree / "file_b.py").write_text("ORIGINAL B\n")

    h_a = calculate_file_sha256(worktree / "file_a.py")
    h_b = calculate_file_sha256(worktree / "file_b.py")

    # Case 1: pre-validation failure (missing file) -> nothing is touched at all
    missing_batch = PatchSet(
        job_id="job-prevalidation",
        base_commit="c1",
        files=[
            FilePatch(
                path="file_a.py",
                operation=PatchOperation.MODIFY,
                patch="NEW A\n",
                sha256_before=h_a,
                sha256_after=_sha256("NEW A\n"),
            ),
            FilePatch(
                path="file_b_missing.py",
                operation=PatchOperation.MODIFY,
                patch="NEW B\n",
                sha256_before=h_b,
                sha256_after=_sha256("NEW B\n"),
            ),
        ],
    )
    ok, err = apply_patch_set(worktree, missing_batch)
    assert ok is False
    assert "does not exist" in str(err)
    assert (worktree / "file_a.py").read_text() == "ORIGINAL A\n"

    # Case 2: failure DURING application (post-hash mismatch on 2nd file) -> file A was already
    # written and must be restored by the rollback journal.
    mid_failure_batch = PatchSet(
        job_id="job-rollback",
        base_commit="c1",
        files=[
            FilePatch(
                path="file_a.py",
                operation=PatchOperation.MODIFY,
                patch="NEW A\n",
                sha256_before=h_a,
                sha256_after=_sha256("NEW A\n"),
            ),
            FilePatch(
                path="file_b.py",
                operation=PatchOperation.MODIFY,
                patch="NEW B\n",
                sha256_before=h_b,
                sha256_after="f" * 64,  # deliberately wrong -> fails after writing
            ),
        ],
    )
    ok2, err2 = apply_patch_set(worktree, mid_failure_batch)
    assert ok2 is False
    assert "rolled back cleanly" in str(err2)
    assert (worktree / "file_a.py").read_text() == "ORIGINAL A\n"
    assert (worktree / "file_b.py").read_text() == "ORIGINAL B\n"


def test_local_uncommitted_change_triggers_conflict(tmp_path: Path) -> None:
    """Local modification to destination repo prior to merge triggers MERGE_CONFLICT."""
    repo = tmp_path / "repo"
    repo.mkdir()
    target_file = repo / "calc.py"
    target_file.write_text("VALUE = 10\n")

    orig_hash = calculate_file_sha256(target_file)

    patch_set = PatchSet(
        job_id="job-conflict",
        base_commit="c1",
        files=[
            FilePatch(
                path="calc.py",
                operation=PatchOperation.MODIFY,
                patch="VALUE = 20\n",
                sha256_before=orig_hash,
                sha256_after=_sha256("VALUE = 20\n"),
            )
        ],
    )

    # Simulate concurrent uncommitted local change on target file before merge
    target_file.write_text("VALUE = 9999\n")

    ok, err = apply_patch_set(repo, patch_set, verify_before_hash=True)
    assert ok is False
    assert "Hash mismatch before applying patch" in str(err)
    # File content preserved without overwrite
    assert target_file.read_text() == "VALUE = 9999\n"


# ---------------------------------------------------------------------------
# Case 17: Full Authorized Flow (AGF-001 - AGF-007)
# ---------------------------------------------------------------------------


def test_authorized_full_pipeline_flow(tmp_path: Path) -> None:
    """Complete end-to-end authorized pipeline succeeds and produces verified changes."""
    repo = tmp_path / "proj"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    target = src / "main.py"
    target.write_text("x = 1\n")

    planner_resp = json.dumps(
        {
            "files_to_modify": ["src/main.py"],
            "preliminary_risk": "MEDIUM",
            "risk_reasons": ["Small value change"],
            "permissions_requested": {
                "read": ["src/main.py"],
                "write": ["src/main.py"],
                "execute": ["pytest"],
            },
            "rationale": "Change x to 2",
        }
    )
    worker_resp = json.dumps(
        {
            "thought": "Set x to 2",
            "propose_patch": {
                "description": "Change x to 2",
                "files": [{"path": "src/main.py", "operation": "MODIFY", "content": "x = 2\n"}],
            },
        }
    )
    config = PipelineConfig(
        repo_root=repo,
        model_id="mock",
        auto_approve=True,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(
        config=config, gateway=_gateway_with(planner_resp, worker_resp)
    )
    result = orchestrator.run("change x to 2 in src/main.py")

    assert result.success is True
    assert result.final_state == JobState.COMPLETE
    assert result.hash_chain_intact is True
    assert target.read_text() == "x = 2\n"
