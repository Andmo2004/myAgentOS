"""Automatic staleness detection and lifecycle transition for knowledge notes according to §22.5."""

from myagentos.core.models.knowledge import NoteStatus, ProjectNote
from myagentos.curator.validator import ANCHOR_PATTERN


class StalenessTracker:
    """Tracks note anchors against modified files to flag stale documentation (§22.5)."""

    @staticmethod
    def update_notes_staleness(
        notes: list[ProjectNote],
        modified_files: set[str],
    ) -> list[ProjectNote]:
        """Transitions verified notes to 'stale' if any of their anchored files were modified."""
        updated: list[ProjectNote] = []

        for note in notes:
            if note.status != NoteStatus.VERIFIED:
                updated.append(note)
                continue

            is_stale = False
            for anchor in note.anchors:
                match = ANCHOR_PATTERN.match(anchor.strip())
                if match:
                    rel_path, _, _ = match.groups()
                    if rel_path in modified_files:
                        is_stale = True
                        break

            if is_stale:
                updated.append(note.model_copy(update={"status": NoteStatus.STALE}))
            else:
                updated.append(note)

        return updated
