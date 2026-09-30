"""Unit tests for controlled taxonomy and normalization."""

from myagentos.categorization.models import TagCategory
from myagentos.categorization.taxonomy import (
    APPLICATIONS,
    CATEGORY_WEIGHTS,
    DOMAINS,
    FRAMEWORKS,
    INFRASTRUCTURE,
    LIFECYCLE,
    REDUNDANCY_SUBSUMED_BY,
    TECHNOLOGIES,
    normalize_tag_label,
    resolve_category,
)


def test_catalogs_defined() -> None:
    """Verify that canonical taxonomies are populated and valid."""
    assert "Developer Tools" in DOMAINS
    assert "E-commerce" in DOMAINS
    assert "CLI" in APPLICATIONS
    assert "Web" in APPLICATIONS
    assert "Python" in TECHNOLOGIES
    assert "FastAPI" in FRAMEWORKS
    assert "Docker" in INFRASTRUCTURE
    assert "Production" in LIFECYCLE


def test_normalization_map() -> None:
    """Verify that alias normalization maps correctly to canonical labels."""
    assert normalize_tag_label("devtools") == "Developer Tools"
    assert normalize_tag_label("developer tools") == "Developer Tools"
    assert normalize_tag_label("ai") == "AI/ML"
    assert normalize_tag_label("machine_learning") == "AI/ML"
    assert normalize_tag_label("nextjs") == "Next.js"
    assert normalize_tag_label("k8s") == "Kubernetes"
    assert normalize_tag_label("postgres") == "PostgreSQL"
    assert normalize_tag_label("opensource") == "Open Source"


def test_resolve_category() -> None:
    """Verify category resolution according to taxonomy catalogs."""
    assert resolve_category("Developer Tools") == TagCategory.DOMAIN
    assert resolve_category("CLI") == TagCategory.APPLICATION
    assert resolve_category("FastAPI") == TagCategory.FRAMEWORK
    assert resolve_category("Python") == TagCategory.TECHNOLOGY
    assert resolve_category("Docker") == TagCategory.INFRASTRUCTURE
    assert resolve_category("Production") == TagCategory.LIFECYCLE


def test_redundancy_rules() -> None:
    """Verify redundancy relationships (e.g. Next.js subsumes React)."""
    assert "Next.js" in REDUNDANCY_SUBSUMED_BY["React"]
    assert "TypeScript" in REDUNDANCY_SUBSUMED_BY["JavaScript"]


def test_category_weights() -> None:
    """Verify domain and framework have higher weights for visibility."""
    assert CATEGORY_WEIGHTS[TagCategory.DOMAIN] > CATEGORY_WEIGHTS[TagCategory.TECHNOLOGY]
    assert CATEGORY_WEIGHTS[TagCategory.FRAMEWORK] > CATEGORY_WEIGHTS[TagCategory.INFRASTRUCTURE]
