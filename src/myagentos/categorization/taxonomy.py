"""Canonical taxonomy and vocabulary definitions for Project Categorization.

Follows §9, §10 of the feature specification:
docs/agentic-os-feature-project-categorization.md
"""

from __future__ import annotations

from myagentos.categorization.models import TagCategory

# Canonical Tag Catalogs by Category (§9)
DOMAINS: set[str] = {
    "E-commerce",
    "Fintech",
    "Health",
    "Education",
    "Productivity",
    "Developer Tools",
    "Analytics",
    "Media",
    "Gaming",
    "Security",
    "AI/ML",
}

APPLICATIONS: set[str] = {
    "Web",
    "API",
    "CLI",
    "Desktop",
    "Mobile",
    "Service",
    "Library",
    "SDK",
    "Data Pipeline",
}

TECHNOLOGIES: set[str] = {
    "Python",
    "TypeScript",
    "JavaScript",
    "Rust",
    "Go",
    "Java",
    "C#",
    "C++",
    "Ruby",
    "PHP",
}

FRAMEWORKS: set[str] = {
    "FastAPI",
    "Django",
    "Flask",
    "Next.js",
    "React",
    "Vue",
    "Svelte",
    "Express",
    "Spring",
}

INFRASTRUCTURE: set[str] = {
    "Docker",
    "Kubernetes",
    "AWS",
    "GCP",
    "Azure",
    "PostgreSQL",
    "Redis",
    "SQLite",
    "MongoDB",
}

LIFECYCLE: set[str] = {
    "Production",
    "Monorepo",
    "Open Source",
    "Prototype",
    "Legacy",
}

# Normalization mapping (lowercased / raw aliases -> canonical label)
NORMALIZATION_MAP: dict[str, str] = {
    # Domains
    "ecommerce": "E-commerce",
    "e-commerce": "E-commerce",
    "fintech": "Fintech",
    "developer_tools": "Developer Tools",
    "developer tools": "Developer Tools",
    "devtools": "Developer Tools",
    "dev-tools": "Developer Tools",
    "analytics": "Analytics",
    "security": "Security",
    "ai/ml": "AI/ML",
    "ai": "AI/ML",
    "ml": "AI/ML",
    "machine_learning": "AI/ML",
    # Applications
    "web": "Web",
    "api": "API",
    "cli": "CLI",
    "desktop": "Desktop",
    "mobile": "Mobile",
    "service": "Service",
    "library": "Library",
    "sdk": "SDK",
    "pipeline": "Data Pipeline",
    "data_pipeline": "Data Pipeline",
    # Technologies
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "rust": "Rust",
    "go": "Go",
    "golang": "Go",
    # Frameworks
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "react": "React",
    "vue": "Vue",
    "svelte": "Svelte",
    "express": "Express",
    # Infrastructure
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "redis": "Redis",
    "sqlite": "SQLite",
    # Lifecycle
    "production": "Production",
    "prod": "Production",
    "monorepo": "Monorepo",
    "open_source": "Open Source",
    "opensource": "Open Source",
    "legacy": "Legacy",
    "prototype": "Prototype",
}

# Redundancy relationships (§10): parent / redundant tags when specific child is present
# e.g., Next.js subsumes React; TypeScript subsumes JavaScript
REDUNDANCY_SUBSUMED_BY: dict[str, list[str]] = {
    "React": ["Next.js"],
    "JavaScript": ["TypeScript", "Next.js", "React"],
    "Web": ["Next.js"],  # If Next.js is present, pure Web is lower information density
}

# Category weights for tag scoring (§10)
CATEGORY_WEIGHTS: dict[TagCategory, float] = {
    TagCategory.DOMAIN: 1.25,
    TagCategory.FRAMEWORK: 1.15,
    TagCategory.APPLICATION: 1.10,
    TagCategory.TECHNOLOGY: 1.00,
    TagCategory.INFRASTRUCTURE: 0.85,
    TagCategory.LIFECYCLE: 0.75,
}


def normalize_tag_label(raw: str) -> str:
    """Normalizes arbitrary raw strings or aliases to canonical catalog label."""
    clean = raw.strip().lower()
    return NORMALIZATION_MAP.get(clean, raw.strip().title())


def resolve_category(label: str) -> TagCategory:
    """Resolves which taxonomy category a canonical tag label belongs to."""
    if label in DOMAINS:
        return TagCategory.DOMAIN
    if label in APPLICATIONS:
        return TagCategory.APPLICATION
    if label in FRAMEWORKS:
        return TagCategory.FRAMEWORK
    if label in TECHNOLOGIES:
        return TagCategory.TECHNOLOGY
    if label in INFRASTRUCTURE:
        return TagCategory.INFRASTRUCTURE
    if label in LIFECYCLE:
        return TagCategory.LIFECYCLE
    return TagCategory.TECHNOLOGY
