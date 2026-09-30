"""Unit tests for DependencyClosureAnalyzer repository mapping and closures (§9.1, §9.2)."""

from pathlib import Path

from myagentos.context.closure import DependencyClosureAnalyzer


def test_dependency_closure_analyzer_map_and_closure(tmp_path: Path) -> None:
    # Set up dummy repo structure
    src_dir = tmp_path / "src" / "pkg"
    src_dir.mkdir(parents=True)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)

    # 1. Manifest
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')

    # 2. Main entrypoint & modules
    (tmp_path / "src" / "cli.py").write_text("import pkg.service\n")
    (src_dir / "__init__.py").write_text("")
    (src_dir / "service.py").write_text("from pkg.models import Item\n")
    (src_dir / "models.py").write_text("class Item: pass\n")

    # 3. Unit test
    (tests_dir / "test_service.py").write_text("import pkg.service\n")

    # Repository map
    repo_map = DependencyClosureAnalyzer.build_repository_map(tmp_path)
    assert repo_map.total_files >= 5
    assert "pyproject.toml" in repo_map.manifest_files
    assert any("cli.py" in e for e in repo_map.key_entrypoints)
    assert any("test_service.py" in t for t in repo_map.test_files)
    assert "src/" in repo_map.tree_repr

    # Dependency closure from seed 'src/pkg/service.py'
    closure = DependencyClosureAnalyzer.compute_dependency_closure(
        seed_files=["src/pkg/service.py"],
        root_dir=tmp_path,
        max_depth=2,
    )

    # Must find models.py (imported) and test_service.py (associated test)
    assert any("models.py" in f for f in closure)
    assert any("test_service.py" in f for f in closure)
