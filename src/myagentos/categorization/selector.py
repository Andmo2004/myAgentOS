"""Selection and scoring algorithm selecting 3-5 non-redundant visible tags.

Follows §6, §10, and §22 of the feature specification:
docs/agentic-os-feature-project-categorization.md
"""

from __future__ import annotations

from myagentos.categorization.models import (
    PresentationOverrides,
    TagCategory,
    TagSource,
    VisibleTag,
)
from myagentos.categorization.taxonomy import (
    CATEGORY_WEIGHTS,
    REDUNDANCY_SUBSUMED_BY,
    normalize_tag_label,
)


class ScoredCandidate:
    def __init__(
        self,
        label: str,
        category: TagCategory,
        confidence: float,
        source: TagSource,
        evidence: list[str],
        pinned: bool = False,
    ) -> None:
        self.label = label
        self.category = category
        self.confidence = confidence
        self.source = source
        self.evidence = evidence
        self.pinned = pinned
        self.score: float = 0.0


def select_visible_tags(
    candidates: list[ScoredCandidate],
    overrides: PresentationOverrides | None = None,
    max_tags: int = 5,
    min_tags: int = 1,
) -> list[VisibleTag]:
    """Selects 3 to 5 visible tags based on evidence, category weights, and anti-redundancy."""
    overrides = overrides or PresentationOverrides()
    hidden_normalized = {t.lower() for t in overrides.hidden_tags}
    pinned_normalized = {t.lower() for t in overrides.pinned_tags}

    # 1. Filter out hidden tags and apply user pinning
    valid_candidates: list[ScoredCandidate] = []
    for c in candidates:
        if c.label.lower() in hidden_normalized:
            continue
        if c.label.lower() in pinned_normalized:
            c.pinned = True
        valid_candidates.append(c)

    # 2. Compute initial scores (§10)
    for c in valid_candidates:
        cat_weight = CATEGORY_WEIGHTS.get(c.category, 1.0)
        evidence_strength = min(len(c.evidence) * 0.25, 1.0)
        pin_bonus = 5.0 if c.pinned else 0.0

        # High confidence gets more weight
        c.score = (c.confidence * 1.5) + (cat_weight * 1.2) + evidence_strength + pin_bonus

    # 3. Sort by score descending
    valid_candidates.sort(key=lambda x: x.score, reverse=True)

    # 4. Selection loop with anti-redundancy penalty
    selected: list[ScoredCandidate] = []
    selected_labels: set[str] = set()
    category_counts: dict[TagCategory, int] = {}

    # First pass: honor pinned items
    for c in valid_candidates:
        if c.pinned and len(selected) < max_tags:
            selected.append(c)
            selected_labels.add(c.label)
            category_counts[c.category] = category_counts.get(c.category, 0) + 1

    # Second pass: diverse and non-redundant candidates
    for c in valid_candidates:
        if len(selected) >= max_tags:
            break
        if c.label in selected_labels:
            continue

        # Check redundancy: if a child tag is already selected that subsumes this tag
        # e.g. If Next.js is selected, React is subsumed
        subsuming_tags = REDUNDANCY_SUBSUMED_BY.get(c.label, [])
        if any(parent in selected_labels for parent in subsuming_tags):
            continue

        # Limit max 2 tags from the exact same category to ensure variety
        if category_counts.get(c.category, 0) >= 2 and not c.pinned:
            continue

        selected.append(c)
        selected_labels.add(c.label)
        category_counts[c.category] = category_counts.get(c.category, 0) + 1

    # Format into final VisibleTag objects
    visible_tags: list[VisibleTag] = []
    for c in selected:
        tag_id = c.label.lower().replace(" ", "_").replace(".", "").replace("/", "_")
        visible_tags.append(
            VisibleTag(
                id=tag_id,
                label=normalize_tag_label(c.label),
                category=c.category,
                confidence=round(c.confidence, 2),
                source=TagSource.USER_PINNED if c.pinned else c.source,
                pinned=c.pinned,
                evidence=c.evidence,
            )
        )

    return visible_tags
