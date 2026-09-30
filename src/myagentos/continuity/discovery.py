"""Deterministic static repository discovery according to §8.2, §9, §11, and §33."""

import ast
import re
from collections import defaultdict
from pathlib import Path

from myagentos.continuity.models import (
    ArchitectureMap,
    EntrypointInfo,
    EvidenceItem,
    EvidenceTier,
    Finding,
    FindingCode,
    FindingSeverity,
    InternalDependencyInfo,
    ModuleInfo,
    ProjectSnapshot,
    ProposedFindingAction,
)

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sh": "shell",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "Private key detected"),
    (
        r"(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
        "Credential assignment",
    ),
    (r"AIza[0-9A-Za-z-_]{35}", "Google API key format"),
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key format"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token"),
]

TODO_PATTERN = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b\s*[:\-]?(.*)", re.IGNORECASE)


def _mask_secret(val: str) -> str:
    """Masks secret value to adhere to §33 preservation constraints."""
    if len(val) <= 6:
        return "***"
    return f"{val[:3]}...{val[-3:]}"


def _detect_languages(repo_root: Path, files: list[str]) -> dict[str, float]:
    """Computes distribution of programming languages in the project."""
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for rel_path in files:
        ext = Path(rel_path).suffix.lower()
        if ext in LANGUAGE_EXTENSIONS:
            lang = LANGUAGE_EXTENSIONS[ext]
            counts[lang] += 1
            total += 1
    if total == 0:
        return {}
    sorted_items = sorted(counts.items(), key=lambda x: -x[1])
    return {lang: round(cnt / total, 3) for lang, cnt in sorted_items}


def _detect_frameworks(repo_root: Path) -> list[str]:
    """Detects active frameworks based on manifests and files."""
    frameworks: set[str] = set()

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
        py_frameworks = [
            "fastapi",
            "flask",
            "django",
            "pytest",
            "pydantic",
            "ruff",
            "mypy",
            "torch",
            "transformers",
        ]
        for fw in py_frameworks:
            if fw in content:
                frameworks.add(fw)

    pkg_json = repo_root / "package.json"
    if pkg_json.is_file():
        content = pkg_json.read_text(encoding="utf-8", errors="ignore").lower()
        node_frameworks = ["react", "vue", "next", "express", "jest", "vite", "typescript"]
        for fw in node_frameworks:
            if fw in content:
                frameworks.add(fw)

    cargo = repo_root / "Cargo.toml"
    if cargo.is_file():
        content = cargo.read_text(encoding="utf-8", errors="ignore").lower()
        for fw in ["tokio", "axum", "actix", "serde"]:
            if fw in content:
                frameworks.add(fw)

    return sorted(frameworks)


def _detect_entrypoints(repo_root: Path, files: list[str]) -> list[EntrypointInfo]:
    """Detects CLI/Service entrypoints from config and conventions."""
    entrypoints: list[EntrypointInfo] = []

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        in_scripts = False
        for line in text.splitlines():
            line_strip = line.strip()
            if line_strip in ("[project.scripts]", "[tool.poetry.scripts]"):
                in_scripts = True
                continue
            if in_scripts:
                if line_strip.startswith("["):
                    in_scripts = False
                elif "=" in line_strip:
                    name, target = [x.strip() for x in line_strip.split("=", 1)]
                    clean_target = target.strip("\"'")
                    path_part = clean_target.split(":")[0].replace(".", "/") + ".py"
                    symbol_part = clean_target.split(":")[-1] if ":" in clean_target else None
                    entrypoints.append(
                        EntrypointInfo(
                            path=path_part,
                            symbol=symbol_part,
                            kind=f"CLI ({name})",
                        )
                    )

    common_names = {"main.py", "app.py", "cli.py", "server.py", "index.ts", "server.ts"}
    for f in files:
        if Path(f).name in common_names and not any(e.path == f for e in entrypoints):
            entrypoints.append(EntrypointInfo(path=f, kind="SERVICE/SCRIPT"))

    return entrypoints


def _is_module_available(repo_root: Path, imp_name: str, available_modules: set[str]) -> bool:
    if any(avail == imp_name or avail.startswith(imp_name + ".") for avail in available_modules):
        return True
    path_variant = imp_name.replace(".", "/")
    candidates = [
        repo_root / f"{path_variant}.py",
        repo_root / path_variant / "__init__.py",
        repo_root / "src" / f"{path_variant}.py",
        repo_root / "src" / path_variant / "__init__.py",
    ]
    if imp_name.startswith("myagentos."):
        sub = imp_name[len("myagentos.") :].replace(".", "/")
        candidates.extend(
            [
                repo_root / "src" / "myagentos" / f"{sub}.py",
                repo_root / "src" / "myagentos" / sub / "__init__.py",
            ]
        )
    return any(c.exists() for c in candidates)


def _scan_python_symbols_and_imports(
    repo_root: Path, py_files: list[str]
) -> tuple[dict[str, list[str]], list[tuple[str, str]], list[tuple[str, str, int]]]:
    """Extracts symbols, internal dependencies, and broken imports using AST."""
    module_symbols: dict[str, list[str]] = defaultdict(list)
    internal_deps: list[tuple[str, str]] = []
    broken_imports: list[tuple[str, str, int]] = []

    available_modules: set[str] = set()
    for rel_path in py_files:
        p = Path(rel_path)
        mod_name = p.with_suffix("").as_posix().replace("/", ".")
        available_modules.add(mod_name)
        if "src." in mod_name:
            available_modules.add(mod_name.replace("src.", ""))

    for rel_path in py_files:
        full_path = repo_root / rel_path
        try:
            tree = ast.parse(
                full_path.read_text(encoding="utf-8", errors="ignore"),
                filename=rel_path,
            )
        except Exception:
            continue

        caller_mod = Path(rel_path).with_suffix("").as_posix().replace("/", ".")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    module_symbols[rel_path].append(node.name)

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imp_name = alias.name
                    if imp_name.startswith(("myagentos", "src")):
                        internal_deps.append((caller_mod, imp_name))
                        if not _is_module_available(repo_root, imp_name, available_modules):
                            broken_imports.append((rel_path, imp_name, node.lineno))

            elif isinstance(node, ast.ImportFrom) and node.module:
                imp_name = node.module
                if imp_name.startswith(("myagentos", "src")):
                    internal_deps.append((caller_mod, imp_name))
                    if not _is_module_available(repo_root, imp_name, available_modules):
                        broken_imports.append((rel_path, imp_name, node.lineno))

    return module_symbols, internal_deps, broken_imports


def run_static_discovery(
    repo_root: str | Path,
    snapshot: ProjectSnapshot,
) -> tuple[ArchitectureMap, list[Finding]]:
    """Runs deterministic static discovery on the snapshot (§8.2, §9, §11, §33)."""
    root = Path(repo_root).resolve()
    files = snapshot.tracked_files

    languages = _detect_languages(root, files)
    frameworks = _detect_frameworks(root)
    entrypoints = _detect_entrypoints(root, files)

    py_files = [f for f in files if f.endswith(".py")]
    symbols_by_file, int_deps_raw, broken_imports_raw = _scan_python_symbols_and_imports(
        root, py_files
    )

    modules: list[ModuleInfo] = []
    module_paths: set[str] = set()
    for f in py_files:
        p = Path(f)
        parent_dir = p.parent.as_posix()
        if parent_dir not in module_paths:
            module_paths.add(parent_dir)
            modules.append(
                ModuleInfo(
                    id=parent_dir.replace("/", "."),
                    path=parent_dir,
                    public_symbols=symbols_by_file.get(f, []),
                    dependencies=[],
                    dependents=[],
                )
            )

    seen_deps: set[tuple[str, str]] = set()
    internal_dependencies: list[InternalDependencyInfo] = []
    for src, dst in int_deps_raw:
        if (src, dst) not in seen_deps:
            seen_deps.add((src, dst))
            internal_dependencies.append(InternalDependencyInfo(from_module=src, to_module=dst))

    arch_map = ArchitectureMap(
        modules=modules,
        entrypoints=entrypoints,
        external_dependencies=[],
        internal_dependencies=internal_dependencies,
        languages=languages,
        frameworks=frameworks,
    )

    findings: list[Finding] = []
    finding_counter = 1

    # 1. Git dirty state finding (§13.2)
    if not snapshot.working_tree.clean:
        uncommitted_count = len(snapshot.working_tree.uncommitted_files)
        findings.append(
            Finding(
                finding_id=f"F-{finding_counter:03d}",
                code=FindingCode.GIT_STATE_DIRTY,
                severity=FindingSeverity.LOW,
                title="Git working tree contains uncommitted changes",
                summary=f"Repository working tree has {uncommitted_count} uncommitted files.",
                evidence=[
                    EvidenceItem(
                        kind=EvidenceTier.OBSERVED,
                        source="git status",
                        observed_value=f"{uncommitted_count} uncommitted files",
                        details={"files": ", ".join(snapshot.working_tree.uncommitted_files[:5])},
                    )
                ],
                confidence=1.0,
                proposed_actions=[
                    ProposedFindingAction(
                        id="A-001",
                        description="Commit or stash changes to ensure reproducible baseline",
                    )
                ],
            )
        )
        finding_counter += 1

    # 2. Secret detection with redaction (§33)
    for rel_path in files:
        fpath = root / rel_path
        if not fpath.is_file() or fpath.stat().st_size > 1_000_000:
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for pat, desc in SECRET_PATTERNS:
            for match in re.finditer(pat, content):
                matched_raw = match.group(0)
                masked = _mask_secret(matched_raw)
                findings.append(
                    Finding(
                        finding_id=f"F-{finding_counter:03d}",
                        code=FindingCode.SECRET_DETECTED,
                        severity=FindingSeverity.HIGH,
                        title=f"Potential credential or secret in {rel_path}",
                        summary=f"{desc} detected in {rel_path}.",
                        evidence=[
                            EvidenceItem(
                                kind=EvidenceTier.OBSERVED,
                                source=rel_path,
                                anchor=f"char:{match.start()}",
                                observed_value=masked,  # Strictly redacted (§33)
                                expected_value="Environment variable or secret manager reference",
                            )
                        ],
                        confidence=0.9,
                        proposed_actions=[
                            ProposedFindingAction(
                                id="A-002",
                                description=(
                                    "Move credential to environment variable and add path to"
                                    " .gitignore"
                                ),
                            )
                        ],
                    )
                )
                finding_counter += 1

    # 3. Broken imports (§13.2)
    for rel_path, imp_mod, lineno in broken_imports_raw:
        findings.append(
            Finding(
                finding_id=f"F-{finding_counter:03d}",
                code=FindingCode.BROKEN_IMPORT,
                severity=FindingSeverity.HIGH,
                title=f"Broken internal import '{imp_mod}' in {rel_path}",
                summary=f"Module {rel_path} attempts to import {imp_mod} which does not exist.",
                evidence=[
                    EvidenceItem(
                        kind=EvidenceTier.DERIVED,
                        source=rel_path,
                        anchor=f"L{lineno}",
                        observed_value=f"import {imp_mod}",
                        expected_value="Resolvable internal module path",
                    )
                ],
                confidence=0.95,
                proposed_actions=[
                    ProposedFindingAction(
                        id="A-003",
                        description=f"Fix import statement or create missing module '{imp_mod}'",
                    )
                ],
            )
        )
        finding_counter += 1

    # 4. TODO accumulation (§11, §13.2)
    todo_matches: list[tuple[str, int, str]] = []
    for rel_path in py_files:
        fpath = root / rel_path
        try:
            lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, 1):
            if m := TODO_PATTERN.search(line):
                todo_matches.append((rel_path, idx, m.group(0).strip()))

    if len(todo_matches) >= 5:
        sample_details = {f"{p}:L{ln}": txt[:50] for p, ln, txt in todo_matches[:5]}
        findings.append(
            Finding(
                finding_id=f"F-{finding_counter:03d}",
                code=FindingCode.TODO_ACCUMULATION,
                severity=FindingSeverity.INFO,
                title=f"Accumulation of {len(todo_matches)} TODO/FIXME comments",
                summary=(
                    f"Discovered {len(todo_matches)} pending TODO/FIXME markers in source files."
                ),
                evidence=[
                    EvidenceItem(
                        kind=EvidenceTier.OBSERVED,
                        source=todo_matches[0][0],
                        anchor=f"L{todo_matches[0][1]}",
                        observed_value=f"{len(todo_matches)} items found",
                        details=sample_details,
                    )
                ],
                confidence=1.0,
            )
        )
        finding_counter += 1

    # 5. Documentation drift: Missing or empty README (§13.2, §28)
    if not (root / "README.md").is_file():
        findings.append(
            Finding(
                finding_id=f"F-{finding_counter:03d}",
                code=FindingCode.DOC_DRIFT,
                severity=FindingSeverity.LOW,
                title="Missing README.md documentation",
                summary="The repository root does not contain a README.md file.",
                evidence=[
                    EvidenceItem(
                        kind=EvidenceTier.OBSERVED,
                        source="README.md",
                        observed_value="File does not exist",
                        expected_value="Root README.md explaining project setup and usage",
                    )
                ],
                confidence=1.0,
            )
        )

    return arch_map, findings
