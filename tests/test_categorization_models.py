"""Unit tests for Project Profile & Categorization data models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from myagentos.categorization.models import (
    ArchitectureProfile,
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


def test_models_immutability() -> None:
    """Verify that models are immutable (frozen=True)."""
    tag = VisibleTag(
        id="python",
        label="Python",
        category=TagCategory.TECHNOLOGY,
        confidence=0.95,
        source=TagSource.DETERMINISTIC,
    )
    with pytest.raises(ValidationError):
        setattr(tag, "confidence", 0.5)

    profile = ProjectProfile(
        project_id="test-proj",
        repository="test-repo",
    )
    with pytest.raises(ValidationError):
        setattr(profile, "status", ProfileStatus.STALE)


def test_visible_tag_validation() -> None:
    """Verify confidence range constraints on VisibleTag."""
    with pytest.raises(ValidationError):
        VisibleTag(
            id="bad",
            label="Bad",
            category=TagCategory.TECHNOLOGY,
            confidence=1.5,  # > 1.0
            source=TagSource.DETERMINISTIC,
        )

    with pytest.raises(ValidationError):
        VisibleTag(
            id="bad",
            label="Bad",
            category=TagCategory.TECHNOLOGY,
            confidence=-0.1,  # < 0.0
            source=TagSource.DETERMINISTIC,
        )


def test_inference_model() -> None:
    """Verify Inference model serialization and defaults."""
    now = datetime.now(UTC)
    inf = Inference(
        key="domain",
        value="Fintech",
        confidence=0.9,
        evidence=["stripe in pyproject.toml"],
        generated_by="semantic_inferencer",
        generated_at=now,
        status="accepted",
    )
    assert inf.key == "domain"
    assert inf.value == "Fintech"
    assert inf.status == "accepted"
    assert inf.abstain_reason is None

    dumped = inf.model_dump()
    assert dumped["confidence"] == 0.9
    assert dumped["evidence"] == ["stripe in pyproject.toml"]


def test_project_profile_serialization() -> None:
    """Verify full ProjectProfile serialization and deserialization."""
    profile = ProjectProfile(
        project_id="my-agent-os",
        repository="myAgentOS",
        status=ProfileStatus.FRESH,
        stack=StackProfile(
            languages=["Python"],
            frameworks=["FastAPI"],
            runtimes=["CPython 3.12"],
        ),
        architecture=ArchitectureProfile(
            application_type=["CLI"],
            monorepo=False,
        ),
        infrastructure=InfrastructureProfile(
            containers=["Docker"],
            ci_cd=["GitHub Actions"],
        ),
        quality=QualityProfile(
            test_frameworks=["pytest"],
            typechecking=True,
            linting=True,
        ),
        visible_tags=[
            VisibleTag(
                id="python",
                label="Python",
                category=TagCategory.TECHNOLOGY,
                confidence=1.0,
                source=TagSource.DETERMINISTIC,
            )
        ],
        presentation_overrides=PresentationOverrides(
            hidden_tags=["Docker"],
            pinned_tags=["Python"],
        ),
        scan_hash="abc123hash",
    )

    json_str = profile.model_dump_json()
    reconstructed = ProjectProfile.model_validate_json(json_str)

    assert reconstructed.project_id == "my-agent-os"
    assert reconstructed.stack.languages == ["Python"]
    assert reconstructed.quality.typechecking is True
    assert reconstructed.visible_tags[0].label == "Python"
    assert reconstructed.presentation_overrides.pinned_tags == ["Python"]
    assert reconstructed.scan_hash == "abc123hash"
