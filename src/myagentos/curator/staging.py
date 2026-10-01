"""Staging manager and restricted propose_project_note tool according to §22.3."""

import re
from pathlib import Path

from myagentos.core.errors import AgenticOSError
from myagentos.core.models.knowledge import ProjectNote

MAX_NOTES_PER_JOB = 3
MAX_NOTE_SIZE_BYTES = 8192  # 8 KB per note (§22.3)


class StagingLimitExceededError(AgenticOSError):
    """Raised when a job exceeds the maximum number or size of staged notes (§22.3)."""


StagingLimitExceeded = StagingLimitExceededError


class StagingOverwriteViolationError(AgenticOSError):
    """Raised when attempting to overwrite existing canonical or staged notes (§22.3)."""


StagingOverwriteViolation = StagingOverwriteViolationError


class NoteStagingManager:
    """Stages Curator notes and publishes verified notes into project-local memory."""

    _safe_component = re.compile(r"[^a-zA-Z0-9_-]")

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._job_note_counts: dict[str, int] = {}

    def get_inbox_path(self, project_id: str = "default") -> Path:
        """Return the project's isolated memory inbox (§22.3)."""
        safe_id = self._safe_component.sub("_", project_id)
        inbox = self.repo_root / ".myagentos" / "memory" / "_inbox" / safe_id
        try:
            inbox.parent.resolve().relative_to(self.repo_root)
        except (OSError, ValueError) as exc:
            raise ValueError("Project memory inbox escapes the repository root") from exc
        inbox.mkdir(parents=True, exist_ok=True)
        self._verify_project_path(inbox)
        return inbox

    def get_project_memory_path(self, project_id: str = "default") -> Path:
        """Return the canonical note directory for one project in this repository."""
        safe_id = self._safe_component.sub("_", project_id)
        notes = self.repo_root / ".myagentos" / "memory" / "projects" / safe_id / "notes"
        try:
            notes.parent.resolve().relative_to(self.repo_root)
        except (OSError, ValueError) as exc:
            raise ValueError("Canonical project memory escapes the repository root") from exc
        notes.mkdir(parents=True, exist_ok=True)
        self._verify_project_path(notes)
        return notes

    def _verify_project_path(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.repo_root)
        except (OSError, ValueError) as exc:
            raise ValueError("Project memory path escapes the repository root") from exc

    def propose_project_note(self, note: ProjectNote) -> Path:
        """Restricted MCP tool implementation (§22.3):

        - Create-only: never overwrites existing canonical or staged notes.
        - Hard limits per job: max 3 notes and max 8 KB per note.
        """
        job_id = note.provenance.job_id
        count = self._job_note_counts.get(job_id, 0)
        if count >= MAX_NOTES_PER_JOB:
            raise StagingLimitExceeded(
                f"Job {job_id} exceeded maximum staged notes limit ({MAX_NOTES_PER_JOB}) (§22.3)"
            )

        content = note.to_markdown()
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_NOTE_SIZE_BYTES:
            raise StagingLimitExceeded(
                f"Note {note.note_id} exceeds maximum size limit of {MAX_NOTE_SIZE_BYTES} bytes "
                f"(actual: {len(content_bytes)} bytes) (§22.3)"
            )

        inbox_dir = self.get_inbox_path(note.project_id)
        safe_note_id = self._safe_component.sub("_", note.note_id)
        note_filename = f"{safe_note_id}.md"
        target_file = inbox_dir / note_filename

        if target_file.exists():
            raise StagingOverwriteViolation(
                f"Note file '{note_filename}' already exists. Staging is create-only (§22.3)"
            )

        target_file.write_text(content, encoding="utf-8")
        self._job_note_counts[job_id] = count + 1

        return target_file

    def publish_verified_note(self, note: ProjectNote) -> Path:
        """Publish only a validated note to canonical project memory, create-only."""
        from myagentos.core.models.knowledge import NoteStatus

        if note.status != NoteStatus.VERIFIED:
            raise ValueError("Only verified Curator notes may enter canonical project memory")
        content = note.to_markdown()
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_NOTE_SIZE_BYTES:
            raise StagingLimitExceeded(
                f"Note {note.note_id} exceeds maximum size limit of {MAX_NOTE_SIZE_BYTES} bytes"
            )

        safe_note_id = self._safe_component.sub("_", note.note_id)
        target_file = self.get_project_memory_path(note.project_id) / f"{safe_note_id}.md"
        try:
            with target_file.open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError as exc:
            raise StagingOverwriteViolation(
                f"Canonical note '{target_file.name}' already exists"
            ) from exc
        try:
            target_file.chmod(0o600)
        except OSError:
            pass
        return target_file

    def list_inbox_notes(self, project_id: str = "default") -> list[Path]:
        """Lists all markdown notes currently staged in the inbox."""
        inbox = self.get_inbox_path(project_id)
        return sorted(inbox.glob("*.md"))
