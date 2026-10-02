"""Tests for modular Skill System Core (§3-§18, §67-§73 of agentic-os-feature-skills.md)."""

from pathlib import Path

import pytest

from myagentos.skills.models import (
    ActiveSkill,
    CircularDependencyError,
    SkillDefinition,
    SkillDependencyDepthError,
)
from myagentos.skills.registry import SkillRegistry
from myagentos.skills.retriever import SkillRetriever


def test_builtin_skills_discovered():
    """Verify built-in skills are discovered with correct lightweight metadata (§3, §14)."""
    registry = SkillRegistry()
    discovered = registry.discover()
    names = {s.name for s in discovered}
    assert {
        "cybersecurity",
        "python",
        "testing",
        "debugging",
        "database",
        "git",
        "research",
    }.issubset(names)

    sec = registry.get_definition("cybersecurity")
    assert sec is not None
    assert sec.source == "builtin"
    assert "security" in sec.tag_set
    assert "oauth" in sec.trigger_set
    assert "python" in sec.requires


def test_jit_loading_only_on_demand(tmp_path: Path):
    """Verify discovery parses frontmatter and does not load full body until load() (§8)."""
    skill_dir = tmp_path / "skills" / "custom"
    skill_dir.mkdir(parents=True)
    body_text = (
        "# Custom Skill Instructions\n\nDeep procedural content that should not load in discovery."
    )
    frontmatter = (
        "---\nname: custom\ndescription: Custom skill\nversion: 1.0.0\n"
        "tags:\n  - custom\nsource: project\n---\n\n"
    )
    (skill_dir / "SKILL.md").write_text(
        f"{frontmatter}{body_text}",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    registry.discover(project_root=tmp_path)
    defn = registry.get_definition("custom")
    assert defn is not None
    assert defn.name == "custom"
    assert not hasattr(defn, "content")  # SkillDefinition is lightweight

    # Active skill loaded on demand
    active = registry.load("custom")
    assert isinstance(active, ActiveSkill)
    assert active.name == "custom"
    assert "Deep procedural content" in active.content


def test_hierarchical_discovery_and_project_precedence(tmp_path: Path):
    """Verify project skills specialize builtin skills with the same name (§10, §11, §68)."""
    project_root = tmp_path / "project"
    project_skills = project_root / "skills" / "python"
    project_skills.mkdir(parents=True)
    content_python = (
        "---\nname: python\ndescription: Project specialized python conventions\n"
        "version: 2.0.0\ntags:\n  - python\n  - custom-api\nsource: project\n---\n\n"
        "Project python rules."
    )
    (project_skills / "SKILL.md").write_text(content_python, encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(project_root=project_root)

    # By name lookup returns the project specialization
    resolved = registry.get_definition("python")
    assert resolved is not None
    assert resolved.source == "project"
    assert resolved.version == "2.0.0"

    # Both definitions are retained in registry by unique ID
    assert registry.get_definition("builtin:python") is not None
    assert registry.get_definition("project:python") is not None


def test_skill_retriever_scoring_and_selection(tmp_path: Path):
    """Verify retriever selects relevant skills and ignores irrelevant ones (§15, §68)."""
    project_root = tmp_path / "project"
    skills_dir = project_root / "skills"
    # Create project skill #api
    api_dir = skills_dir / "api"
    api_dir.mkdir(parents=True)
    content_api = (
        "---\nname: api\ndescription: FastAPI REST endpoint engineering\n"
        "version: 1.0.0\ntags:\n  - api\n  - rest\ntriggers:\n  - fastapi\n  - endpoints\n"
        "source: project\n---\n\nAPI instructions."
    )
    (api_dir / "SKILL.md").write_text(content_api, encoding="utf-8")
    # Create user skill #latex in a separate directory
    user_dir = tmp_path / "user_skills" / "latex"
    user_dir.mkdir(parents=True)
    content_latex = (
        "---\nname: latex\ndescription: LaTeX document compilation\n"
        "version: 1.0.0\ntags:\n  - latex\n  - tex\ntriggers:\n  - pdflatex\n"
        "source: user\n---\n\nLaTeX instructions."
    )
    (user_dir / "SKILL.md").write_text(content_latex, encoding="utf-8")

    registry = SkillRegistry()
    registry.discover(project_root=project_root, user_skills_dir=tmp_path / "user_skills")
    retriever = SkillRetriever(registry)

    # Query: "Revisa la autenticación OAuth del backend"
    selected = retriever.select("Revisa la autenticación OAuth del backend")
    selected_names = [s.name for s in selected]

    assert "cybersecurity" in selected_names
    assert "latex" not in selected_names

    # Query: "API FastAPI" -> picks api and python, not latex (§68)
    selected_api = retriever.select("API FastAPI")
    api_names = [s.name for s in selected_api]
    assert "api" in api_names
    assert "latex" not in api_names


def test_project_isolation(tmp_path: Path):
    """A session in Project A must never discover skills from Project B (§69)."""
    proj_a = tmp_path / "proj_a"
    skill_a = proj_a / "skills" / "internal-platform"
    skill_a.mkdir(parents=True)
    content_a = (
        "---\nname: internal-platform\ndescription: Platform A\n"
        "version: 1.0.0\ntags: [platform]\nsource: project\n---\n\nPlatform."
    )
    (skill_a / "SKILL.md").write_text(content_a, encoding="utf-8")

    proj_b = tmp_path / "proj_b"
    skill_b = proj_b / "skills" / "game-engine"
    skill_b.mkdir(parents=True)
    content_b = (
        "---\nname: game-engine\ndescription: Game B\n"
        "version: 1.0.0\ntags: [game]\nsource: project\n---\n\nGame."
    )
    (skill_b / "SKILL.md").write_text(content_b, encoding="utf-8")

    registry_a = SkillRegistry()
    registry_a.discover(project_root=proj_a)
    assert registry_a.get_definition("internal-platform") is not None
    assert registry_a.get_definition("game-engine") is None

    registry_b = SkillRegistry()
    registry_b.discover(project_root=proj_b)
    assert registry_b.get_definition("game-engine") is not None
    assert registry_b.get_definition("internal-platform") is None


def test_dependency_resolution_and_topological_order():
    """Verify dependency graph resolution in topological order without duplicates (§17, §70)."""
    registry = SkillRegistry()
    # Mock skill definitions: secure-api -> requires [python, cybersecurity]
    # cybersecurity -> requires [python]
    registry.register_definition(
        SkillDefinition(
            id="project:secure-api",
            name="secure-api",
            description="Secure API",
            version="1.0.0",
            tags=("api",),
            triggers=(),
            source="project",
            path=Path("/fake/secure_api"),
            requires=("cybersecurity",),
        )
    )
    registry.register_definition(
        SkillDefinition(
            id="builtin:cybersecurity",
            name="cybersecurity",
            description="Security",
            version="1.0.0",
            tags=("security",),
            triggers=(),
            source="builtin",
            path=Path("/fake/sec"),
            requires=("python",),
        )
    )
    registry.register_definition(
        SkillDefinition(
            id="builtin:python",
            name="python",
            description="Python",
            version="1.0.0",
            tags=("python",),
            triggers=(),
            source="builtin",
            path=Path("/fake/py"),
            requires=(),
        )
    )

    retriever = SkillRetriever(registry)
    root = registry.get_definition("secure-api")
    assert root is not None
    resolved = retriever.resolve_dependencies([root])

    names = [s.name for s in resolved]
    assert names == ["python", "cybersecurity", "secure-api"]
    assert len(names) == len(set(names))


def test_circular_dependency_detection():
    """Verify circular dependencies A -> B -> A raise CircularDependencyError (§17)."""
    registry = SkillRegistry()
    registry.register_definition(
        SkillDefinition(
            id="builtin:skill-a",
            name="skill-a",
            description="A",
            version="1.0.0",
            tags=(),
            triggers=(),
            source="builtin",
            path=Path("/fake/a"),
            requires=("skill-b",),
        )
    )
    registry.register_definition(
        SkillDefinition(
            id="builtin:skill-b",
            name="skill-b",
            description="B",
            version="1.0.0",
            tags=(),
            triggers=(),
            source="builtin",
            path=Path("/fake/b"),
            requires=("skill-a",),
        )
    )

    retriever = SkillRetriever(registry)
    skill_a = registry.get_definition("skill-a")
    assert skill_a is not None

    with pytest.raises(CircularDependencyError, match="Circular dependency detected"):
        retriever.resolve_dependencies([skill_a])


def test_dependency_depth_limit():
    """Verify chains deeper than max depth raise SkillDependencyDepthError (§18)."""
    registry = SkillRegistry()
    for i in range(5):
        next_req = (f"chain-{i + 1}",) if i < 4 else ()
        registry.register_definition(
            SkillDefinition(
                id=f"builtin:chain-{i}",
                name=f"chain-{i}",
                description=f"Chain {i}",
                version="1.0.0",
                tags=(),
                triggers=(),
                source="builtin",
                path=Path(f"/fake/{i}"),
                requires=next_req,
            )
        )

    retriever = SkillRetriever(registry)
    chain_0 = registry.get_definition("chain-0")
    assert chain_0 is not None

    with pytest.raises(SkillDependencyDepthError, match="exceeds max depth"):
        retriever.resolve_dependencies([chain_0], max_depth=3)
