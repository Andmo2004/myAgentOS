"""Verification Guard pipeline and integrity enforcement according to §13."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.failure import FailureCode
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS
from myagentos.sandbox.base import ExecutionLimits, SandboxDriver
from myagentos.verification.manifest import TestManifest
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
    """Deterministic pipeline executing protected checks inside the Code Sandbox (§13)."""

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
    ) -> VerificationResult:
        """Executes the complete verification pipeline in order (§13.1)."""
        stage_summaries: dict[str, str] = {}

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

        # Stage 2: Compile / Typecheck
        if compile_cmd:
            res_compile = self.sandbox_driver.run_command(compile_cmd, worktree_path, limits)
            if not res_compile.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.SYNTAX_ERROR,
                    diagnostics=f"Compilation/Typecheck failed: {res_compile.stderr}",
                    restored_paths=restored,
                    stage_summaries={"COMPILE": res_compile.stderr},
                )
            stage_summaries["COMPILE"] = "PASS"

        # Stage 3: Lint / Static Analysis
        if lint_cmd:
            res_lint = self.sandbox_driver.run_command(lint_cmd, worktree_path, limits)
            if not res_lint.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Linter failed: {res_lint.stderr}",
                    restored_paths=restored,
                    stage_summaries={"LINT": res_lint.stderr},
                )
            stage_summaries["LINT"] = "PASS"

        # Stage 4: Protected Acceptance Tests
        if protected_test_cmd:
            res_prot = self.sandbox_driver.run_command(protected_test_cmd, worktree_path, limits)
            if not res_prot.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Protected acceptance tests failed: {res_prot.stderr}",
                    restored_paths=restored,
                    stage_summaries={"PROTECTED_TESTS": res_prot.stderr},
                )
            stage_summaries["PROTECTED_TESTS"] = "PASS"

        # Stage 5: Project Tests
        if project_test_cmd:
            res_proj = self.sandbox_driver.run_command(project_test_cmd, worktree_path, limits)
            if not res_proj.succeeded:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Project tests failed: {res_proj.stderr}",
                    restored_paths=restored,
                    stage_summaries={"PROJECT_TESTS": res_proj.stderr},
                )
            stage_summaries["PROJECT_TESTS"] = "PASS"

        # Stage 6: Test Manifest Validation (§13.5)
        if manifest:
            exec_ids = executed_test_ids or set()
            fail_ids = failed_test_ids or set()
            skip_ids = skipped_test_ids or set()
            manifest_ok, reason = manifest.validate_candidate(exec_ids, fail_ids, skip_ids)
            if not manifest_ok:
                return VerificationResult(
                    passed=False,
                    failure_code=FailureCode.TEST_FAILURE,
                    diagnostics=f"Test manifest validation failed: {reason}",
                    restored_paths=restored,
                    stage_summaries={"MANIFEST_CHECK": reason or "FAIL"},
                )
            stage_summaries["MANIFEST_CHECK"] = "PASS"

        return VerificationResult(
            passed=True,
            failure_code=None,
            diagnostics="All verification checks passed cleanly",
            restored_paths=restored,
            stage_summaries=stage_summaries,
        )
