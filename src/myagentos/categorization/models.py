"""Data models for Project Categorization & Project Profile.

Follows §6, §7, §9, and §12 of the feature specification:
docs/agentic-os-feature-project-categorization.md

System View: rich Project Profile with facts, inferences, confidence and evidence.
User View: 3-5 non-redundant visible tags.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProfileStatus(StrEnum):
    """Lifecycle status of the Project Profile (§12)."""

    MISSING = "missing"
    SCANNING = "scanning"
    FRESH = "fresh"
    STALE = "stale"
    FAILED = "failed"


class TagCategory(StrEnum):
    """Controlled taxonomy categories for tags (§9)."""

    DOMAIN = "domain"
    APPLICATION = "application"
    TECHNOLOGY = "technology"
    FRAMEWORK = "framework"
    INFRASTRUCTURE = "infrastructure"
    LIFECYCLE = "lifecycle"


class TagSource(StrEnum):
    """Origin of a tag assignment (§7, §22)."""

    DETERMINISTIC = "deterministic"
    INFERRED = "inferred"
    HYBRID = "hybrid"
    USER_PINNED = "user_pinned"


class VisibleTag(BaseModel):
    """A single canonical tag projected to the User View (3-5 tags, §6, §9)."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    category: TagCategory
    confidence: float = Field(ge=0.0, le=1.0)
    source: TagSource
    pinned: bool = False
    evidence: list[str] = Field(default_factory=list)


class Inference(BaseModel):
    """Semantic inference with explicit evidence and confidence tracking (§7, §24)."""

    model_config = ConfigDict(frozen=True)

    key: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    generated_by: str = "model"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "accepted"  # "accepted", "abstain", "rejected"
    abstain_reason: str | None = None


class StackProfile(BaseModel):
    """Observed technical stack details (§6)."""

    model_config = ConfigDict(frozen=True)

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    runtimes: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    build_tools: list[str] = Field(default_factory=list)


class ArchitectureProfile(BaseModel):
    """Observed and inferred application architectural properties (§6)."""

    model_config = ConfigDict(frozen=True)

    styles: list[str] = Field(default_factory=list)
    application_type: list[str] = Field(default_factory=list)
    frontend: list[str] = Field(default_factory=list)
    backend: list[str] = Field(default_factory=list)
    api: list[str] = Field(default_factory=list)
    workers: list[str] = Field(default_factory=list)
    monorepo: bool = False


class InfrastructureProfile(BaseModel):
    """Observed infrastructure and deployment footprint (§6)."""

    model_config = ConfigDict(frozen=True)

    containers: list[str] = Field(default_factory=list)
    cloud: list[str] = Field(default_factory=list)
    ci_cd: list[str] = Field(default_factory=list)
    orchestration: list[str] = Field(default_factory=list)
    observability: list[str] = Field(default_factory=list)


class QualityProfile(BaseModel):
    """Observed testing, typing, and linting environment (§6)."""

    model_config = ConfigDict(frozen=True)

    test_frameworks: list[str] = Field(default_factory=list)
    typechecking: bool = False
    linting: bool = False
    formatting: bool = False


class CategorizerMeta(BaseModel):
    """Metadata of the categorizer engine run (§6)."""

    model_config = ConfigDict(frozen=True)

    version: str = "1.0"
    strategy: str = "deterministic+semantic"
    scan_hash: str = ""


class PresentationOverrides(BaseModel):
    """User manual overrides for tags display (§22)."""

    model_config = ConfigDict(frozen=True)

    hidden_tags: list[str] = Field(default_factory=list)
    pinned_tags: list[str] = Field(default_factory=list)


class ProjectProfile(BaseModel):
    """Structured internal representation of the repository profile (§6).

    Optimized for system understanding and reuse by Local Router, Skills Runtime,
    Context Compiler, and Mya conversational interface.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    project_id: str
    repository: str
    base_revision: str = "HEAD"
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: ProfileStatus = ProfileStatus.FRESH

    stack: StackProfile = Field(default_factory=StackProfile)
    architecture: ArchitectureProfile = Field(default_factory=ArchitectureProfile)
    infrastructure: InfrastructureProfile = Field(default_factory=InfrastructureProfile)
    quality: QualityProfile = Field(default_factory=QualityProfile)

    inferences: list[Inference] = Field(default_factory=list)
    visible_tags: list[VisibleTag] = Field(default_factory=list)
    presentation_overrides: PresentationOverrides = Field(default_factory=PresentationOverrides)

    scan_hash: str = ""
    categorizer_version: str = "1.0"
