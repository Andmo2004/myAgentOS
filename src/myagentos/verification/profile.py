"""Verification profile configuration and auto-detection (§13, AGF-004)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from myagentos.verification.manifest import TestManifest


class VerificationProfile(BaseModel):
    """Reliable, project-level verification profile defining required checks (§13, AGF-004)."""

    model_config = ConfigDict(frozen=True)

    compile_cmd: str | None = None
    lint_cmd: str | None = None
    protected_test_cmd: str | None = None
    project_test_cmd: str | None = None
    manifest: TestManifest | None = None
    is_non_code: bool = False
    skip_reason: str | None = None

    @classmethod
    def for_non_code(cls, reason: str = "Documentation or non-code task") -> "VerificationProfile":
        """Explicit profile for documentation or non-code changes with documented rationale."""
        return cls(is_non_code=True, skip_reason=reason)

    @classmethod
    def default_for_repo(cls, repo_root: Path) -> "VerificationProfile":
        """Infers appropriate default verification commands from repository structure."""
        has_python = any(repo_root.glob("*.py")) or any(repo_root.glob("src/**/*.py"))
        compile_cmd = None
        if has_python:
            compile_cmd = "python3 -m compileall -q ."

        test_cmd = None
        if (
            (repo_root / "tests").is_dir()
            or (repo_root / "pytest.ini").exists()
            or (repo_root / "pyproject.toml").exists()
        ):
            test_cmd = "pytest -q"

        return cls(
            compile_cmd=compile_cmd,
            project_test_cmd=test_cmd,
            is_non_code=False,
        )
