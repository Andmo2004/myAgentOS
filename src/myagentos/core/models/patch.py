"""Structured PatchSet and file patch records according to §12."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PatchOperation(StrEnum):
    """Permitted patch operations (§12)."""

    MODIFY = "modify"
    CREATE = "create"
    DELETE = "delete"
    RENAME = "rename"


class FilePatch(BaseModel):
    """Integrity-sealed patch for an individual file (§12)."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(..., description="Target file path relative to repo root")
    operation: PatchOperation
    patch: str = Field(..., description="Unified diff or full contents proposed by the Worker")
    old_path: str | None = Field(default=None, description="Source path for rename operations")
    mode_before: str = Field(default="100644", description="POSIX mode before patch")
    mode_after: str = Field(default="100644", description="POSIX mode after patch")
    sha256_before: str = Field(..., description="SHA-256 hash of original file content")
    sha256_after: str = Field(..., description="SHA-256 hash of new file content after patch")

    @property
    def diff_line_count(self) -> int:
        """Counts added, modified or removed lines from unified diff patch."""
        count = 0
        for line in self.patch.splitlines():
            if (line.startswith("+") and not line.startswith("+++")) or (
                line.startswith("-") and not line.startswith("---")
            ):
                count += 1
        return count if count > 0 else len(self.patch.splitlines())


class PatchSet(BaseModel):
    """Complete patch set sealed with job ID and base commit hashes (§12)."""

    model_config = ConfigDict(frozen=True)

    job_id: str = Field(..., description="Job identifier stamped by the controller")
    base_commit: str = Field(..., description="Base commit stamped by the controller")
    files: list[FilePatch] = Field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.files)

    @property
    def total_diff_lines(self) -> int:
        return sum(f.diff_line_count for f in self.files)

    @property
    def affected_paths(self) -> set[str]:
        paths = set()
        for f in self.files:
            paths.add(f.path)
            if f.old_path:
                paths.add(f.old_path)
        return paths

    @property
    def has_mode_changes(self) -> bool:
        return any(f.mode_before != f.mode_after for f in self.files)
