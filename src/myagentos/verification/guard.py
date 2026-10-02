"""Verification Guard pipeline and integrity enforcement according to §13 and AGF-004."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.failure import FailureCode
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS
from myagentos.sandbox.base import ExecutionLimits, SandboxDriver
from myagentos.verification.manifest import TestManifest
from myagentos.verification.profile import VerificationProfile
from myagentos.verification.protector import restore_protected_paths


class VerificationResult(BaseModel):
    """Structured report produced by the Verification Guard (§13.1)."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    failure_code: FailureCode | None = None
    diagnostics: str = ""
    restored_paths: list[str] = Field(default_factory=list)
    stage_summaries: dict[str, str] = Field(default_factory=dict)


class VerificationGuard:
    """Deterministic pipeline executing protected checks inside the Code Sandbox (§13, AGF-004)."""

    def __init__(
        self,
        sandbox_driver: SandboxDriver,
        protected_paths: list[str] | None = None,
    ) -> None:
        self.sandbox_driver = sandbox_driver
        self.protected_paths = protected_paths or DEFAULT_PROTECTED_PATHS

    def verify(
        self,
        worktree_path: Path,
        base_commit: str,
        compile_cmd: str | None = None,
        lint_cmd: str | None = None,
        protected_test_cmd: str | None = None,
        project_test_cmd: str | None = None,
        manifest: TestManifest | None = None,
        executed_test_ids: set[str] | None = None,
        failed_test_ids: set[str] | None = None,
        skipped_test_ids: set[str] | None = None,
        limits: ExecutionLimits | None = None,
        profile: VerificationProfile | None = None,
    ) -> VerificationResult:
        """Executes the complete verification pipeline in order (§13.1, AGF-004)."""
        stage_summaries: dict[str, str] = {}

        # Resolve configuration from profile if provided
        c_cmd = compile_cmd or (profile.compile_cmd if profile else None)
        l_cmd = lint_cmd or (profile.lint_cmd if profile else None)
        prot_cmd = protected_test_cmd or (profile.protected_test_cmd if profile else None)
        proj_cmd = project_test_cmd or (profile.project_test_cmd if profile else None)
        test_manifest = manifest or (profile.manifest if profile else None)
        is_non_code = profile.is_non_code if profile else False
        skip_reason = profile.skip_reason if profile else None

        # Stage 1: Restore protected harness and test files from base_commit (§13.3)
        restored = restore_protected_paths(
            worktree_path=worktree_path,
            base_commit=base_commit,
            protected_paths=self.protected_paths,
        )
        if restored:
            stage_summaries["PROTECTED_RESTORE"] = (
                f"Restored {len(restored)} protected files from {base_commit}: {restored}"
            )

        # Stage 2: Compile / Typecheck / Syntax validation (AGF-004)
        if c_cmd:
            res_compile = self.sandbox_driver.run_command(c_cmd, worktree_path, limits)
            if not res_compile.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.SYNTAX_ERROR,
                    diagnostics=f"Compilation/Typecheck failed: {res_compile.stderr}",
                    restored_paths=restored,
                    stage_summaries={"COMPILE": f"FAIL: {res_compile.stderr}"},
                )
            stage_summaries["COMPILE"] = "PASS"
        else:
            # Fallback syntax validation on candidate Python files
            syntax_errors = []
            checked_py = 0
            for py_file in worktree_path.rglob("*.py"):
                if any(part in py_file.parts for part in (".git", ".venv", "__pycache__")):
                    continue
                checked_py += 1
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    compile(content, str(py_file), "exec")
                except SyntaxError as syn_err:
                    syntax_errors.append(f"{py_file.name}:{syn_err.lineno}: {syn_err.msg}")

            if syntax_errors:
                err_msg = "; ".join(syntax_errors)
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.SYNTAX_ERROR,
                    diagnostics=f"Python syntax error in candidate: {err_msg}",
                    restored_paths=restored,
                    stage_summaries={"COMPILE": f"FAIL: {err_msg}"},
                )
            if checked_py > 0:
                stage_summaries["COMPILE"] = "PASS"

        # Stage 3: Lint / Static Analysis
        if l_cmd:
            res_lint = self.sandbox_driver.run_command(l_cmd, worktree_path, limits)
            if not res_lint.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Linter failed: {res_lint.stderr}",
                    restored_paths=restored,
                    stage_summaries={"LINT": f"FAIL: {res_lint.stderr}"},
                )
            stage_summaries["LINT"] = "PASS"

        # Stage 4: Protected Acceptance Tests
        if prot_cmd:
            res_prot = self.sandbox_driver.run_command(prot_cmd, worktree_path, limits)
            if not res_prot.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Protected acceptance tests failed: {res_prot.stderr}",
                    restored_paths=restored,
                    stage_summaries={"PROTECTED_TESTS": f"FAIL: {res_prot.stderr}"},
                )
            stage_summaries["PROTECTED_TESTS"] = "PASS"

        # Stage 5: Project Tests
        if proj_cmd:
            res_proj = self.sandbox_driver.run_command(proj_cmd, worktree_path, limits)
            if not res_proj.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Project tests failed: {res_proj.stderr}",
                    restored_paths=restored,
                    stage_summaries={"PROJECT_TESTS": f"FAIL: {res_proj.stderr}"},
                )
            stage_summaries["PROJECT_TESTS"] = "PASS"

        # Stage 6: Test Manifest Validation (§13.5)
        if test_manifest:
            exec_ids = executed_test_ids or set()
            fail_ids = failed_test_ids or set()
            skip_ids = skipped_test_ids or set()
            manifest_ok, reason = test_manifest.validate_candidate(exec_ids, fail_ids, skip_ids)
            if not manifest_ok:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Test manifest validation failed: {reason}",
                    restored_paths=restored,
                    stage_summaries={"MANIFEST_CHECK": reason or "FAIL"},
                )
            stage_summaries["MANIFEST_CHECK"] = "PASS"

        # Verification Gate Check (AGF-004): zero stages executed cannot pass for code tasks
        executed_stages = [k for k in stage_summaries if k != "PROTECTED_RESTORE"]
        if not executed_stages:
            if is_non_code:
                stage_summaries["NON_CODE_CHECK"] = (
                    f"SKIPPED: {skip_reason or 'Documentation task'}"
                )
            else:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.CONFIG_ERROR,
                    diagnostics=(
                        "Zero verification stages were executed for code changes. "
                        "A verification profile with applicable checks is mandatory (AGF-004)."
                    ),
                    restored_paths=restored,
                    stage_summaries={"VERIFY_GATE": "NOT_RUN"},
                )

        return VerificationResult(
            passed=True,
            failure_code=None,
            diagnostics="All verification checks passed cleanly",
            restored_paths=restored,
            stage_summaries=stage_summaries,
        )
