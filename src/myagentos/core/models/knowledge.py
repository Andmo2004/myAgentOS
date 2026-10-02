"""Knowledge note domain models, lifecycle states, and provenance according to §22."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from myagentos.context.models import CompiledContext
from myagentos.core.models.data_policy import DataClassification
from myagentos.core.models.patch import PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.verification.guard import VerificationResult


class NoteStatus(StrEnum):
    """Deterministic lifecycle state of a knowledge note (§22.5)."""

    PROPOSED = "proposed"  # Staged in _inbox/, pending deterministic validation
    VERIFIED = "verified"  # Anchors confirmed in commit, free of secrets
    STALE = "stale"  # Content at anchor path has changed in repository
    SUPERSEDED = "superseded"  # Replaced by a more recent note or ADR
    REJECTED = "rejected"  # Broken anchor or classified secret detected


class NoteProvenance(BaseModel):
    """Immutable provenance and model metadata (§22.6)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    base_commit: str
    model: str
    prompt_version: str = "curator-v2.1"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProjectNote(BaseModel):
    """Structured knowledge note managed in staging/canonical project memory (§22.3, §22.6)."""

    model_config = ConfigDict(frozen=True)

    note_id: str
    schema_version: str = "1.0.0"
    project_id: str = "default"
    status: NoteStatus = NoteStatus.PROPOSED
    trust: Literal["untrusted"] = "untrusted"  # Always untrusted (§19.1, §22.6)
    classification: DataClassification = DataClassification.INTERNAL
    anchors: list[str] = Field(default_factory=list)
    provenance: NoteProvenance
    title: str
    purpose: str = ""
    decisions: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    file_path: str | None = None

    def to_markdown(self) -> str:
        """Serializes the note into markdown with YAML frontmatter (§22.6)."""
        anchor_lines = "\n".join(f'  - "{a}"' for a in self.anchors)
        rejection_block = ""
        if self.rejection_reasons:
            reasons = "\n".join(f'  - "{r}"' for r in self.rejection_reasons)
            rejection_block = f"rejection_reasons:\n{reasons}\n"

        frontmatter = (
            "---\n"
            f'note_id: "{self.note_id}"\n'
            f'schema_version: "{self.schema_version}"\n'
            f'project_id: "{self.project_id}"\n'
            f"status: {self.status.value}\n"
            f"trust: {self.trust}\n"
            f"classification: {self.classification.value}\n"
            f"anchors:\n{anchor_lines}\n"
            f"{rejection_block}"
            "provenance:\n"
            f'  job_id: "{self.provenance.job_id}"\n'
            f'  base_commit: "{self.provenance.base_commit}"\n'
            f'  model: "{self.provenance.model}"\n'
            f'  prompt_version: "{self.provenance.prompt_version}"\n'
            f'  generated_at: "{self.provenance.generated_at.isoformat()}"\n'
            "---\n\n"
        )

        decisions_sec = "\n".join(f"- {d}" for d in self.decisions) or "- None"
        lessons_sec = "\n".join(f"- {item}" for item in self.lessons) or "- None"

        body = (
            f"# {self.title}\n\n"
            f"## Purpose\n{self.purpose or 'N/A'}\n\n"
            f"## Decisions\n{decisions_sec}\n\n"
            f"## Lessons Learned\n{lessons_sec}\n"
        )
        return frontmatter + body


class CuratorInput(BaseModel):
    """Context provided to the Curator role adhering to the Input Boundary (§22.2)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    project_id: str = "default"
    patch_set: PatchSet
    plan: PlanSpec
    verification: VerificationResult | None = None
    base_commit: str
    extracted_facts: CompiledContext | None = None


class CuratorResult(BaseModel):
    """Result produced by the Curator role post-merge (§22.2)."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    notes: list[ProjectNote] = Field(default_factory=list)
    success: bool = True
    summary: str = ""
    model_used: str = ""
    tokens_used: int = 0
