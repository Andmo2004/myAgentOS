"""Repository tree mapping and dependency closure analysis (§9.1, §9.2, AUD-005)."""

import os
from collections import deque
from pathlib import Path

from myagentos.context.extractor import StructuralExtractor
from myagentos.context.models import RepositoryMap

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".agents",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "node_modules",
    ".egg-info",
}

MANIFEST_NAMES = {
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
}


class DependencyClosureAnalyzer:
    """Computes repo map and dependency closures from seed target files (§9.1, §9.2)."""

    @classmethod
    def build_repository_map(cls, root_dir: Path, max_tree_lines: int = 150) -> RepositoryMap:
        """Scans the repository and produces a clean structural map."""
        source_files: list[str] = []
        test_files: list[str] = []
        manifest_files: list[str] = []
        entrypoints: list[str] = []

        tree_lines: list[str] = [f"{root_dir.name}/"]

        for root, dirs, files in os.walk(root_dir):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]

            rel_root = Path(root).relative_to(root_dir)
            indent = "  " * (len(rel_root.parts) if rel_root.parts else 0)

            if rel_root.parts and len(tree_lines) < max_tree_lines:
                tree_lines.append(f"{indent}📁 {rel_root.name}/")

            for f in sorted(files):
                if f.startswith("."):
                    continue
                rel_f_path = (rel_root / f).as_posix()
                if rel_f_path.startswith("./"):
                    rel_f_path = rel_f_path[2:]

                if len(tree_lines) < max_tree_lines:
                    tree_lines.append(f"{indent}  📄 {f}")

                # Classify file
                if f in MANIFEST_NAMES:
                    manifest_files.append(rel_f_path)
                elif "test" in f.lower() or "tests/" in rel_f_path:
                    test_files.append(rel_f_path)
                elif f in ("main.py", "cli.py", "app.py", "__main__.py"):
                    entrypoints.append(rel_f_path)
                    source_files.append(rel_f_path)
                elif f.endswith((".py", ".ts", ".js", ".go", ".rs")):
                    source_files.append(rel_f_path)

        if len(tree_lines) >= max_tree_lines:
            tree_lines.append("  ... (remaining tree truncated for budget)")

        return RepositoryMap(
            root_path=root_dir.as_posix(),
            tree_repr="\n".join(tree_lines),
            total_files=len(source_files) + len(test_files) + len(manifest_files),
            key_entrypoints=entrypoints,
            test_files=test_files,
            manifest_files=manifest_files,
            source_files=source_files,
        )

    @classmethod
    def compute_dependency_closure(
        cls,
        seed_files: list[str],
        root_dir: Path,
        max_depth: int = 2,
        max_files: int = 20,
    ) -> list[str]:
        """Calculates internal dependency closure for seed files (§9.2, AUD-005)."""
        visited: set[str] = set()
        closure: list[str] = []
        queue: deque[tuple[str, int]] = deque((f, 0) for f in seed_files)

        # Pre-index Python modules in repo
        module_to_file = cls._index_python_modules(root_dir)

        while queue and len(closure) < max_files:
            rel_path, depth = queue.popleft()
            if rel_path in visited:
                continue
            visited.add(rel_path)

            if rel_path not in seed_files:
                closure.append(rel_path)

            if depth >= max_depth:
                continue

            full_path = root_dir / rel_path
            if not full_path.is_file():
                continue

            summary = StructuralExtractor.extract_file(full_path, rel_path)

            # Discover internal imports
            for imp in summary.imports:
                target_file = cls._resolve_module(imp, module_to_file)
                if target_file and target_file not in visited:
                    queue.append((target_file, depth + 1))

            # Also discover matching tests for seed files
            if depth == 0:
                matching_test = cls._find_matching_test(rel_path, root_dir)
                if matching_test and matching_test not in visited:
                    queue.append((matching_test, depth + 1))

        return closure

    @classmethod
    def _index_python_modules(cls, root_dir: Path) -> dict[str, str]:
        """Builds a map from dotted module names to relative file paths."""
        mapping: dict[str, str] = {}
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in files:
                if f.endswith(".py"):
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(root_dir).as_posix()
                    # e.g., src/myagentos/core/models/event.py
                    # Candidate module names:
                    # 1. relative to root: src.myagentos.core.models.event
                    parts = list(full_p.relative_to(root_dir).parts)
                    if parts[-1].endswith(".py"):
                        parts[-1] = parts[-1][:-3]
                    if parts[-1] == "__init__":
                        parts = parts[:-1]

                    mod_full = ".".join(parts)
                    mapping[mod_full] = rel_p

                    # 2. If starts with 'src.', also index without 'src.'
                    if parts and parts[0] == "src":
                        mod_trimmed = ".".join(parts[1:])
                        mapping[mod_trimmed] = rel_p

                    # 3. Just filename stem (e.g. 'event')
                    stem = Path(f).stem
                    if stem not in mapping and stem != "__init__":
                        mapping[stem] = rel_p

        return mapping

    @classmethod
    def _resolve_module(cls, import_str: str, index: dict[str, str]) -> str | None:
        """Resolves an import string to an internal relative file path if present."""
        if import_str in index:
            return index[import_str]

        # Try prefix matching (e.g. from myagentos.core.models.event import Event)
        parts = import_str.split(".")
        for i in range(len(parts), 0, -1):
            sub_mod = ".".join(parts[:i])
            if sub_mod in index:
                return index[sub_mod]

        return None

    @classmethod
    def _find_matching_test(cls, rel_path: str, root_dir: Path) -> str | None:
        """Finds corresponding unit test for a source file."""
        stem = Path(rel_path).stem
        if stem.startswith("test_"):
            return None

        candidates = [
            f"tests/test_{stem}.py",
            f"tests/{stem}_test.py",
            f"test/test_{stem}.py",
        ]
        for c in candidates:
            if (root_dir / c).is_file():
                return c

        return None
