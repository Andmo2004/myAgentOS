"""Unit tests for ContextCompiler context building, budget management, and expansion (§9)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from myagentos.context.compiler import ContextCompiler
from myagentos.context.models import ContextExpansionRequest, ContextKind
from myagentos.continuity.models import (
    FindingCode,
    FindingSeverity,
    ProjectFinding,
    ProjectSnapshot,
    WorkingTreeState,
)
from myagentos.core.models.data_policy import TrustTag
from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.core.models.token import CapabilityToken, NetworkScope, TokenLimits


def _create_token(
    read_scope: list[str] | None = None,
    write_scope: list[str] | None = None,
) -> CapabilityToken:
    return CapabilityToken(
        job_id="job-ctx-1",
        worker_id="worker-1",
        risk_level=RiskLevel.LOW,
        read_scope=read_scope or ["src/**", "tests/**"],
        write_scope=write_scope or ["src/**"],
        execute_scope=["pytest"],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(max_files=5, max_diff_lines=200, max_steps=10),
        trust=TrustTag.UNTRUSTED,
        base_commit="c-123456",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )


def test_compile_plan_context(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_file = src_dir / "calc.py"
    target_file.write_text("def multiply(a: int, b: int) -> int:\n    return a * b\n")

    compiler = ContextCompiler(repo_root=tmp_path)
    ctx = compiler.compile_plan_context(
        job_id="job-1",
        prompt="Implement divide function",
        seed_paths=["src/calc.py"],
        base_commit="c-100",
    )

    assert ctx.context_kind == ContextKind.PLAN_CONTEXT
    assert "PLANNER" in ctx.stable_prefix
    assert "calc.py" in ctx.stable_prefix
    assert "def multiply(a: int, b: int) -> int: ..." in ctx.stable_prefix
    # Crucial §9.2 check: No function body in PLAN_CONTEXT!
    assert "return a * b" not in ctx.stable_prefix
    assert "Implement divide function" in ctx.variable_suffix
    assert ctx.total_estimated_tokens > 0

    full_prompt = ctx.render_prompt()
    assert ctx.stable_prefix in full_prompt
    assert ctx.variable_suffix in full_prompt


def test_compile_worker_context_and_permission_scoping(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f1 = src_dir / "module_a.py"
    f1.write_text("def func_a(): return 'A'\n")

    f2 = src_dir / "secret.key"
    f2.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    f_outside = docs_dir / "internal.md"
    f_outside.write_text("# Internal Doc\n")

    plan = PlanSpec(
        plan_id="p-1",
        job_id="job-1",
        base_commit="c-100",
        files_to_modify=["src/module_a.py", "src/secret.key", "docs/internal.md"],
    )

    # Token only grants read to src/**
    token = _create_token(read_scope=["src/**"])
    compiler = ContextCompiler(repo_root=tmp_path)

    ctx = compiler.compile_worker_context(
        job_id="job-1",
        prompt="Update module A",
        plan=plan,
        token=token,
    )

    assert ctx.context_kind == ContextKind.WORKER_CONTEXT
    # Target file in scope with body included
    assert "def func_a(): return 'A'" in ctx.variable_suffix

    # Secret file should be redacted (§18)
    assert "[REDACTED: SECRET DETECTED BY POLICY §18]" in ctx.variable_suffix

    # Target file outside token read scope denied (§9.2, §23)
    assert "[READ PERMISSION DENIED BY CAPABILITY TOKEN]" in ctx.variable_suffix


def test_compile_knowledge_context(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f = src_dir / "api.py"
    f.write_text("def ping() -> str:\n    return 'pong'\n")

    patch = FilePatch(
        path="src/api.py",
        operation=PatchOperation.CREATE,
        patch="+def ping() -> str:\n+    return 'pong'\n",
        sha256_before="",
        sha256_after="hash123",
    )
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="c-1",
        files=[patch],
    )

    compiler = ContextCompiler(repo_root=tmp_path)
    ctx = compiler.compile_knowledge_context(
        job_id="job-1",
        patch_set=patch_set,
        base_commit="c-2",
    )

    assert ctx.context_kind == ContextKind.KNOWLEDGE_CONTEXT
    assert "src/api.py" in ctx.variable_suffix
    assert "api.py:ping" in ctx.variable_suffix




def test_compile_continuation_context(tmp_path: Path) -> None:
    snapshot = ProjectSnapshot(
        snapshot_id="snap-1",
        repository="myagentos",
        base_commit="c-999",
        branch="main",
        working_tree=WorkingTreeState(clean=True, content_hash="whash123"),
        tracked_files=["src/auth.py", "tests/test_auth.py"],
        project_size_bytes=4096,
    )
    findings = [
        ProjectFinding(
            finding_id="f-1",
            code=FindingCode.TEST_FAILURE,
            severity=FindingSeverity.HIGH,
            title="Unit tests failing in auth",
            summary="AssertionError in test_login",
        )
    ]

    compiler = ContextCompiler(repo_root=tmp_path)
    ctx = compiler.compile_continuation_context(
        job_id="job-cont-1",
        snapshot=snapshot,
        findings=findings,
        synthesis_doc="All systems operational except auth.",
    )

    assert ctx.context_kind == ContextKind.CONTINUATION_CONTEXT
    assert "CONTINUITY_ANALYST" in ctx.stable_prefix
    assert "TEST_FAILURE" in ctx.variable_suffix
    assert "Unit tests failing in auth" in ctx.variable_suffix
    assert "All systems operational except auth." in ctx.variable_suffix


def test_context_expansion_flow(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    allowed_file = src_dir / "helper.py"
    allowed_file.write_text("def helper(): pass\n")

    secret_file = src_dir / ".env"
    secret_file.write_text("SECRET_KEY=123456\n")

    token = _create_token(read_scope=["src/helper.py"])
    compiler = ContextCompiler(repo_root=tmp_path)

    # 1. Allowed expansion
    req_allowed = ContextExpansionRequest(
        reason="Need helper",
        symbols=["helper"],
        paths_suggested=["src/helper.py"],
    )
    res_allowed = compiler.expand_context(req_allowed, token, None)  # type: ignore[arg-type]
    assert res_allowed.approved is True
    assert "src/helper.py" in res_allowed.expanded_paths
    assert "def helper(): pass" in res_allowed.content_by_path["src/helper.py"]

    # 2. Denied: outside read scope requires token renegotiation (§9.3)
    req_denied = ContextExpansionRequest(
        reason="Need repo file outside scope",
        symbols=[],
        paths_suggested=["src/other.py"],
    )
    res_denied = compiler.expand_context(req_denied, token, None)  # type: ignore[arg-type]
    assert res_denied.approved is False
    assert res_denied.requires_token_renegotiation is True

    # 3. Denied: path traversal attempt (§9.6)
    req_traversal = ContextExpansionRequest(
        reason="Escape attempt",
        symbols=[],
        paths_suggested=["../../../etc/passwd"],
    )
    res_traversal = compiler.expand_context(req_traversal, token, None)  # type: ignore[arg-type]
    assert res_traversal.approved is False
    assert any("Security violation" in r for r in res_traversal.rejection_reasons)
