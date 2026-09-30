"""Unit tests for deterministic static detector."""

from pathlib import Path

from myagentos.categorization.detector import detect_repository_facts


def test_detect_python_fastapi_repo(tmp_path: Path) -> None:
    """Verify detection on a synthetic Python FastAPI repo."""
    (tmp_path / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "my-fastapi-app"
dependencies = [
    "fastapi>=0.100.0",
    "pytest>=8.0.0",
]
[project.scripts]
mycli = "main:cli"

[tool.mypy]
strict = true

[tool.ruff]
line-length = 100
"""
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.py").write_text("def test_ok(): pass\n")

    result = detect_repository_facts(tmp_path)

    assert "Python" in result.stack.languages
    assert "FastAPI" in result.stack.frameworks
    assert "CLI" in result.architecture.application_type
    assert "API" in result.architecture.application_type
    assert "Docker" in result.infrastructure.containers
    assert "GitHub Actions" in result.infrastructure.ci_cd
    assert "pytest" in result.quality.test_frameworks
    assert result.quality.typechecking is True
    assert result.quality.linting is True
    assert "Production" in result.evidence_by_tag  # CI/CD + tests + containers


def test_detect_node_nextjs_repo(tmp_path: Path) -> None:
    """Verify detection on a synthetic Node Next.js repo."""
    (tmp_path / "app.tsx").write_text("export default function Page() { return <div />; }")
    (tmp_path / "package.json").write_text(
        """
{
  "name": "next-sample",
  "dependencies": {
    "next": "14.0.0",
    "react": "18.2.0"
  },
  "devDependencies": {
    "typescript": "5.0.0"
  }
}
"""
    )
    (tmp_path / "tsconfig.json").write_text("{}")

    result = detect_repository_facts(tmp_path)

    assert "TypeScript" in result.stack.languages
    assert "Next.js" in result.stack.frameworks
    assert "React" in result.stack.frameworks
    assert "Web" in result.architecture.application_type
    assert result.quality.typechecking is True


def test_detect_current_repo() -> None:
    """Verify detection on the actual myAgentOS repo."""
    repo_root = Path.cwd()
    result = detect_repository_facts(repo_root)

    assert "Python" in result.stack.languages
    assert "CLI" in result.architecture.application_type
    assert result.quality.typechecking is True
    assert result.quality.linting is True
    assert result.observed_facts_count > 0
