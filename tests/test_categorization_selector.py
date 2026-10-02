"""Unit tests for tag selection, anti-redundancy, and user overrides."""

from myagentos.categorization.models import (
    PresentationOverrides,
    TagCategory,
    TagSource,
)
from myagentos.categorization.selector import ScoredCandidate, select_visible_tags


def test_select_visible_tags_max_count() -> None:
    """Verify that selected tags never exceed max_tags (5 by default)."""
    candidates = [
        ScoredCandidate("Python", TagCategory.TECHNOLOGY, 1.0, TagSource.DETERMINISTIC, ["src"]),
        ScoredCandidate(
            "FastAPI", TagCategory.FRAMEWORK, 1.0, TagSource.DETERMINISTIC, ["pyproject"]
        ),
        ScoredCandidate(
            "CLI", TagCategory.APPLICATION, 1.0, TagSource.DETERMINISTIC, ["entrypoint"]
        ),
        ScoredCandidate("Developer Tools", TagCategory.DOMAIN, 0.9, TagSource.INFERRED, ["docs"]),
        ScoredCandidate(
            "Docker", TagCategory.INFRASTRUCTURE, 0.9, TagSource.DETERMINISTIC, ["Dockerfile"]
        ),
        ScoredCandidate(
            "PostgreSQL", TagCategory.INFRASTRUCTURE, 0.9, TagSource.DETERMINISTIC, ["deps"]
        ),
        ScoredCandidate("Production", TagCategory.LIFECYCLE, 0.8, TagSource.DETERMINISTIC, ["ci"]),
    ]

    selected = select_visible_tags(candidates, max_tags=5)
    assert 3 <= len(selected) <= 5


def test_select_visible_tags_anti_redundancy() -> None:
    """Verify anti-redundancy rules (Next.js subsumes React; TypeScript subsumes JavaScript)."""
    candidates = [
        ScoredCandidate("Next.js", TagCategory.FRAMEWORK, 1.0, TagSource.DETERMINISTIC, ["next"]),
        ScoredCandidate("React", TagCategory.FRAMEWORK, 1.0, TagSource.DETERMINISTIC, ["react"]),
        ScoredCandidate("TypeScript", TagCategory.TECHNOLOGY, 1.0, TagSource.DETERMINISTIC, ["ts"]),
        ScoredCandidate("JavaScript", TagCategory.TECHNOLOGY, 0.8, TagSource.DETERMINISTIC, ["js"]),
        ScoredCandidate("Web", TagCategory.APPLICATION, 0.9, TagSource.DETERMINISTIC, ["pages"]),
    ]

    selected = select_visible_tags(candidates, max_tags=5)
    selected_labels = [t.label for t in selected]

    assert "Next.js" in selected_labels
    assert "React" not in selected_labels  # Subsumed by Next.js
    assert "TypeScript" in selected_labels
    assert "JavaScript" not in selected_labels  # Subsumed by TypeScript


def test_select_visible_tags_user_overrides() -> None:
    """Verify that hidden tags are removed and pinned tags are guaranteed selected."""
    candidates = [
        ScoredCandidate("Python", TagCategory.TECHNOLOGY, 1.0, TagSource.DETERMINISTIC, ["src"]),
        ScoredCandidate(
            "FastAPI", TagCategory.FRAMEWORK, 1.0, TagSource.DETERMINISTIC, ["pyproject"]
        ),
        ScoredCandidate(
            "Docker", TagCategory.INFRASTRUCTURE, 0.9, TagSource.DETERMINISTIC, ["Dockerfile"]
        ),
        ScoredCandidate("Legacy", TagCategory.LIFECYCLE, 0.5, TagSource.DETERMINISTIC, ["old"]),
    ]

    overrides = PresentationOverrides(
        hidden_tags=["Docker"],
        pinned_tags=["Legacy"],
    )

    selected = select_visible_tags(candidates, overrides=overrides)
    selected_labels = [t.label for t in selected]

    assert "Docker" not in selected_labels
    assert "Legacy" in selected_labels

    legacy_tag = next(t for t in selected if t.label == "Legacy")
    assert legacy_tag.pinned is True
    assert legacy_tag.source == TagSource.USER_PINNED
