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
    """Manages the isolated staging inbox at .myagentos/vault/projects/{project_id}/_inbox/."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._job_note_counts: dict[str, int] = {}

    def get_inbox_path(self, project_id: str = "default") -> Path:
        """Returns the isolated inbox directory for a given project (§22.3)."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)
        inbox = self.repo_root / ".myagentos" / "vault" / "projects" / safe_id / "_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        return inbox

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
        note_filename = f"{note.note_id}.md"
        target_file = inbox_dir / note_filename

        if target_file.exists():
            raise StagingOverwriteViolation(
                f"Note file '{note_filename}' already exists. Staging is create-only (§22.3)"
            )

        target_file.write_text(content, encoding="utf-8")
        self._job_note_counts[job_id] = count + 1

        return target_file

    def list_inbox_notes(self, project_id: str = "default") -> list[Path]:
        """Lists all markdown notes currently staged in the inbox."""
        inbox = self.get_inbox_path(project_id)
        return sorted(inbox.glob("*.md"))
