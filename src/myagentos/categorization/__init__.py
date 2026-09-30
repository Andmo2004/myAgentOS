"""Project Categorization & Profile package for Agentic OS.

Follows docs/agentic-os-feature-project-categorization.md.
"""

from myagentos.categorization.detector import (
    DeterministicDetectionResult,
    detect_repository_facts,
)
from myagentos.categorization.fingerprint import (
    ScanFingerprint,
    calculate_fingerprint,
)
from myagentos.categorization.inferencer import (
    DomainInferenceSchema,
    SemanticInferencer,
)
from myagentos.categorization.models import (
    ArchitectureProfile,
    CategorizerMeta,
    Inference,
    InfrastructureProfile,
    PresentationOverrides,
    ProfileStatus,
    ProjectProfile,
    QualityProfile,
    StackProfile,
    TagCategory,
    TagSource,
    VisibleTag,
)
from myagentos.categorization.selector import (
    ScoredCandidate,
    select_visible_tags,
)
from myagentos.categorization.service import ProjectCategorizationService
from myagentos.categorization.taxonomy import (
    APPLICATIONS,
    DOMAINS,
    FRAMEWORKS,
    INFRASTRUCTURE,
    LIFECYCLE,
    TECHNOLOGIES,
    normalize_tag_label,
    resolve_category,
)

__all__ = [
    "APPLICATIONS",
    "ArchitectureProfile",
    "CategorizerMeta",
    "DOMAINS",
    "DeterministicDetectionResult",
    "DomainInferenceSchema",
    "FRAMEWORKS",
    "INFRASTRUCTURE",
    "Inference",
    "InfrastructureProfile",
    "LIFECYCLE",
    "PresentationOverrides",
    "ProfileStatus",
    "ProjectCategorizationService",
    "ProjectProfile",
    "QualityProfile",
    "ScanFingerprint",
    "ScoredCandidate",
    "SemanticInferencer",
    "StackProfile",
    "TECHNOLOGIES",
    "TagCategory",
    "TagSource",
    "VisibleTag",
    "calculate_fingerprint",
    "detect_repository_facts",
    "normalize_tag_label",
    "resolve_category",
    "select_visible_tags",
]
