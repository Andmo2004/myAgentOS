"""Deterministic static detector extracting observed repository facts and signals.

Follows §4.1, §7, §8 (Fase B & C) of the feature specification:
docs/agentic-os-feature-project-categorization.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from myagentos.categorization.models import (
    ArchitectureProfile,
    InfrastructureProfile,
    QualityProfile,
    StackProfile,
)

# Common language extension mappings
LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
}


class DeterministicDetectionResult:
    """Aggregated container for all deterministically observed facts and their evidence."""

    def __init__(self) -> None:
        self.stack = StackProfile()
        self.architecture = ArchitectureProfile()
        self.infrastructure = InfrastructureProfile()
        self.quality = QualityProfile()
        self.evidence_by_tag: dict[str, list[str]] = {}
        self.observed_facts_count: int = 0
        self.raw_signals: dict[str, Any] = {}


def _read_json_safe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def detect_repository_facts(repo_root: Path) -> DeterministicDetectionResult:
    """Inspects manifests, file extensions, and directory structure deterministically."""
    result = DeterministicDetectionResult()
    evidence = result.evidence_by_tag

    # 1. Languages by file extensions
    lang_counts: dict[str, int] = {}
    ignored_dirs = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
    total_files = 0

    try:
        for file_path in repo_root.rglob("*"):
            if total_files > 5000:
                break
            if any(part in ignored_dirs or part.startswith(".") for part in file_path.parts[:-1]):
                continue
            if file_path.is_file():
                total_files += 1
                ext = file_path.suffix.lower()
                lang = LANG_EXTENSIONS.get(ext)
                if lang:
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1
    except Exception:
        pass

    # Sort languages by prevalence
    detected_languages = [
        lang for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    for lang in detected_languages:
        evidence.setdefault(lang, []).append(
            f"Detected {lang_counts[lang]} files with {lang} extensions"
        )

    # 2. Python Manifest Inspection
    python_deps: set[str] = set()
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace").lower()
        evidence.setdefault("Python", []).append("Found pyproject.toml")
        if "fastapi" in text:
            python_deps.add("fastapi")
            evidence.setdefault("FastAPI", []).append("pyproject.toml specifies fastapi dependency")
        if "django" in text:
            python_deps.add("django")
            evidence.setdefault("Django", []).append("pyproject.toml specifies django dependency")
        if "flask" in text:
            python_deps.add("flask")
            evidence.setdefault("Flask", []).append("pyproject.toml specifies flask dependency")
        if "pytest" in text:
            python_deps.add("pytest")
            evidence.setdefault("Testing", []).append("pyproject.toml configures pytest")
        if "textual" in text or "click" in text or "typer" in text:
            python_deps.add("cli_framework")
            evidence.setdefault("CLI", []).append("pyproject.toml includes CLI/TUI framework")
        if "[project.scripts]" in text or "console_scripts" in text:
            evidence.setdefault("CLI", []).append("pyproject declares console_scripts entrypoint")
        if "postgresql" in text or "psycopg" in text or "asyncpg" in text:
            evidence.setdefault("PostgreSQL", []).append("pyproject includes PostgreSQL drivers")
        if "redis" in text:
            evidence.setdefault("Redis", []).append("pyproject.toml includes Redis dependency")

    requirements = repo_root / "requirements.txt"
    if requirements.is_file():
        req_text = requirements.read_text(encoding="utf-8", errors="replace").lower()
        if "fastapi" in req_text:
            python_deps.add("fastapi")
            evidence.setdefault("FastAPI", []).append("requirements.txt specifies fastapi")
        if "django" in req_text:
            python_deps.add("django")
            evidence.setdefault("Django", []).append("requirements.txt specifies django")
        if "flask" in req_text:
            python_deps.add("flask")
            evidence.setdefault("Flask", []).append("requirements.txt specifies flask")

    # 3. Node/TypeScript Manifest Inspection
    package_json = repo_root / "package.json"
    if package_json.is_file():
        pkg = _read_json_safe(package_json)
        all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        all_deps_keys = {k.lower() for k in all_deps}

        if "next" in all_deps_keys:
            evidence.setdefault("Next.js", []).append("package.json specifies next dependency")
        if "react" in all_deps_keys:
            evidence.setdefault("React", []).append("package.json specifies react dependency")
        if "vue" in all_deps_keys:
            evidence.setdefault("Vue", []).append("package.json specifies vue dependency")
        if "svelte" in all_deps_keys:
            evidence.setdefault("Svelte", []).append("package.json specifies svelte dependency")
        if "express" in all_deps_keys:
            evidence.setdefault("Express", []).append("package.json specifies express dependency")
        if "typescript" in all_deps_keys:
            evidence.setdefault("TypeScript", []).append("package.json specifies typescript")
        if "bin" in pkg:
            evidence.setdefault("CLI", []).append("package.json specifies bin executable")

    # 4. Infrastructure & Container Detection
    containers: list[str] = []
    if (repo_root / "Dockerfile").is_file():
        containers.append("Docker")
        evidence.setdefault("Docker", []).append("Dockerfile present in root")
    has_compose = (
        (repo_root / "docker-compose.yml").is_file()
        or (repo_root / "docker-compose.yaml").is_file()
    )
    if has_compose:
        containers.append("Docker Compose")
        evidence.setdefault("Docker", []).append("docker-compose file present")

    # 5. CI/CD Detection
    ci_cd: list[str] = []
    if (repo_root / ".github" / "workflows").is_dir():
        ci_cd.append("GitHub Actions")
        evidence.setdefault("CI/CD", []).append(".github/workflows present")
    if (repo_root / ".gitlab-ci.yml").is_file():
        ci_cd.append("GitLab CI")
        evidence.setdefault("CI/CD", []).append(".gitlab-ci.yml present")

    # 6. Architectural Patterns & Applications
    app_types: list[str] = []
    if "CLI" in evidence:
        app_types.append("CLI")
    if "Next.js" in evidence or "React" in evidence or (repo_root / "templates").is_dir():
        app_types.append("Web")
        evidence.setdefault("Web", []).append("Frontend framework or template directory present")
    has_api_signals = (
        "FastAPI" in evidence
        or "Flask" in evidence
        or "Express" in evidence
        or (repo_root / "api").is_dir()
    )
    if has_api_signals:
        app_types.append("API")
        evidence.setdefault("API", []).append("REST/API framework or api/ directory present")

    # 7. Frameworks Aggregation
    detected_frameworks: list[str] = []
    for fw in ["FastAPI", "Django", "Flask", "Next.js", "React", "Vue", "Svelte", "Express"]:
        if fw in evidence:
            detected_frameworks.append(fw)

    # 8. Databases Aggregation
    detected_databases: list[str] = []
    for db in ["PostgreSQL", "Redis", "SQLite", "MongoDB"]:
        if db in evidence:
            detected_databases.append(db)

    # 9. Quality Profile
    test_frameworks: list[str] = []
    if (repo_root / "tests").is_dir() or (repo_root / "test").is_dir():
        test_frameworks.append("pytest" if "Python" in detected_languages else "tests")
        evidence.setdefault("Testing", []).append("tests/ directory detected")

    pyproject_text = (
        pyproject.read_text(encoding="utf-8", errors="replace").lower()
        if pyproject.is_file()
        else ""
    )
    typechecking = (
        (repo_root / "tsconfig.json").is_file()
        or ("mypy" in pyproject_text)
    )
    linting = (
        (repo_root / ".eslintrc.json").is_file()
        or ("ruff" in pyproject_text)
    )

    # Compile result structures
    result.stack = StackProfile(
        languages=detected_languages,
        frameworks=detected_frameworks,
        databases=detected_databases,
        build_tools=["uv", "pip"] if (repo_root / "uv.lock").is_file() else [],
    )
    result.architecture = ArchitectureProfile(
        application_type=app_types,
        monorepo=(repo_root / "pnpm-workspace.yaml").is_file(),
    )
    result.infrastructure = InfrastructureProfile(
        containers=containers,
        ci_cd=ci_cd,
    )
    result.quality = QualityProfile(
        test_frameworks=test_frameworks,
        typechecking=typechecking,
        linting=linting,
    )
    result.observed_facts_count = len(evidence)

    # Production lifecycle heuristic (§6)
    if ci_cd and test_frameworks and containers:
        evidence.setdefault("Production", []).append("CI/CD, tests, and containers detected")

    return result
