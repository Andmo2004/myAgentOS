"""Deterministic validator of knowledge note anchors and secrets according to §22.4 and AUD-018."""

import re
from pathlib import Path

from myagentos.context.extractor import StructuralExtractor
from myagentos.context.security import SECRET_CONTENT_PATTERNS
from myagentos.core.models.knowledge import NoteStatus, ProjectNote

ANCHOR_PATTERN = re.compile(r"^([^:]+):([^@]+)@([a-zA-Z0-9._-]+)$")

# Additional heuristic secret patterns for knowledge notes (AUD-018)
KNOWLEDGE_SECRET_PATTERNS = [
    re.compile(
        r"(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]+)['\"]", re.IGNORECASE),
]


class DeterministicNoteValidator:
    """Validates note anchors and ensures zero secret leakage without LLM (§22.4, AUD-018)."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def validate_anchors(self, note: ProjectNote) -> list[str]:
        """Verifies that all referenced anchors exist in the repository tree (§22.4)."""
        findings: list[str] = []

        if not note.anchors:
            findings.append("Note has no anchors. At least one anchor is required (§22.2).")
            return findings

        for anchor_str in note.anchors:
            match = ANCHOR_PATTERN.match(anchor_str.strip())
            if not match:
                findings.append(
                    f"Malformed anchor '{anchor_str}'. "
                    "Expected 'file:symbol@commit' or 'file:line@commit'"
                )
                continue

            rel_path, target, _ = match.groups()
            target_path = self.repo_root / rel_path

            if not target_path.exists() or not target_path.is_file():
                findings.append(f"Anchor file '{rel_path}' does not exist in repository")
                continue

            try:
                content = target_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                findings.append(f"Cannot read anchor file '{rel_path}': {e}")
                continue

            if target.isdigit():
                line_no = int(target)
                line_count = len(content.splitlines())
                if line_no < 1 or line_no > line_count:
                    findings.append(
                        f"Anchor line '{line_no}' out of bounds in '{rel_path}' "
                        f"({line_count} lines)"
                    )
            else:
                # Target is a symbol name
                summary = StructuralExtractor.extract_file(target_path, rel_path)
                symbol_names = {s.name for s in summary.symbols}
                if target not in symbol_names and target not in content:
                    findings.append(
                        f"Anchor symbol '{target}' not found in '{rel_path}'"
                    )

        return findings

    def scan_secrets(self, note: ProjectNote) -> list[str]:
        """Detects passwords, API keys, private keys, or tokens in note content (AUD-018)."""
        findings: list[str] = []

        full_text = "\n".join(
            [
                note.title,
                note.purpose,
                *note.decisions,
                *note.lessons,
                note.to_markdown(),
            ]
        )

        # 1. Context security standard patterns
        for pat in SECRET_CONTENT_PATTERNS:
            if pat.search(full_text):
                findings.append(
                    f"Detected secret pattern matching regex '{pat.pattern}' (§18.3, AUD-018)"
                )

        # 2. Knowledge specific credential strings
        for kpat in KNOWLEDGE_SECRET_PATTERNS:
            if kpat.search(full_text):
                findings.append(
                    f"Detected potential credential matching regex '{kpat.pattern}' (AUD-018)"
                )

        return findings

    def validate_and_transition(self, note: ProjectNote) -> ProjectNote:
        """Runs all deterministic checks and transitions note to VERIFIED or REJECTED (§22.4)."""
        anchor_errors = self.validate_anchors(note)
        secret_errors = self.scan_secrets(note)

        all_errors = anchor_errors + secret_errors

        if not all_errors:
            return note.model_copy(
                update={"status": NoteStatus.VERIFIED, "rejection_reasons": []}
            )

        return note.model_copy(
            update={"status": NoteStatus.REJECTED, "rejection_reasons": all_errors}
        )
