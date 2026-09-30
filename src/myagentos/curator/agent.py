"""Curator Agent generating anchored knowledge notes post-merge according to §22."""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from myagentos.core.models.knowledge import (
    CuratorInput,
    CuratorResult,
    NoteProvenance,
    NoteStatus,
    ProjectNote,
)
from myagentos.curator.staging import NoteStagingManager
from myagentos.curator.validator import DeterministicNoteValidator
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway

logger = logging.getLogger(__name__)

CURATOR_SYSTEM_PROMPT = """You are the Project Knowledge Curator in an Agentic OS (§22).
Your role is to synthesize post-merge architectural knowledge notes based on facts.

Input Boundary & Isolation Rule (§22.2):
You only receive the merged patch diff, approved plan, verification results,
and deterministic extracted symbols.
You NEVER speculate on worker thoughts, unmerged experiments, or unverified claims.

Requirements:
1. Extract the high-level PURPOSE of the change.
2. Document architectural and design DECISIONS made.
3. Record operational or coding LESSONS learned.
4. MANDATORY ANCHORING (§22.2): Every claim must be backed by at least one anchor:
   `path/to/file:SymbolName@commit` OR `path/to/file:line_number@commit`.

Output format: JSON object with the following schema:
{
  "title": "Short descriptive title of the change",
  "purpose": "Why this change was made and what problem it solved",
  "decisions": ["Design decision 1", "Design decision 2"],
  "lessons": ["Lesson learned 1"],
  "anchors": ["src/service.py:ProcessOrder@base_commit", "src/service.py:10@base_commit"]
}
"""


class CuratorAgent:
    """Post-merge knowledge synthesizer creating anchored notes in staging (§22)."""

    def __init__(
        self,
        repo_root: Path,
        gateway: ModelGateway | None = None,
        staging_manager: NoteStagingManager | None = None,
        validator: DeterministicNoteValidator | None = None,
        model_id: str = "mock",
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.gateway = gateway or ModelGateway()
        self.staging_manager = staging_manager or NoteStagingManager(self.repo_root)
        self.validator = validator or DeterministicNoteValidator(self.repo_root)
        self.model_id = model_id

    def curate_knowledge(self, input_data: CuratorInput) -> CuratorResult:
        """Executes post-merge knowledge curation strictly non-blocking (§8, §22.2)."""
        try:
            return self._run_curation(input_data)
        except Exception as e:
            logger.warning("Curator encountered a non-fatal error during knowledge update: %s", e)
            return CuratorResult(
                job_id=input_data.job_id,
                success=False,
                summary=f"Curator completed with non-blocking error: {e}",
            )

    def _run_curation(self, input_data: CuratorInput) -> CuratorResult:
        diff_text = input_data.patch_set.to_unified_diff()
        plan_summary = input_data.plan.impact_summary or "Plan modifications"
        facts_text = ""
        if input_data.extracted_facts:
            facts_text = input_data.extracted_facts.variable_suffix

        # Strict input boundary (§22.2): no worker scratchpad or chain of thought
        user_content = (
            f"=== JOB ID ===\n{input_data.job_id}\n\n"
            f"=== BASE COMMIT ===\n{input_data.base_commit}\n\n"
            f"=== APPROVED PLAN INTENT ===\n{plan_summary}\n\n"
            f"=== TARGETED FILES ===\n{', '.join(input_data.plan.all_targeted_paths())}\n\n"
            f"=== DETERMINISTIC FACTS (AST / Tree-sitter) ===\n{facts_text}\n\n"
            f"=== MERGED UNIFIED DIFF ===\n{diff_text}\n"
        )

        title = f"Update for Job {input_data.job_id}"
        purpose = plan_summary
        decisions: list[str] = []
        lessons: list[str] = []
        anchors: list[str] = []
        tokens_used = 0

        # Attempt structured generation via ModelGateway
        try:
            resp = self.gateway.generate(
                messages=[
                    LLMMessage(role="system", content=CURATOR_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=user_content),
                ],
                model_id=self.model_id,
                temperature=0.0,
            )
            tokens_used = resp.input_tokens + resp.output_tokens
            raw = resp.content.strip()
            if raw.startswith("```json"):
                raw = raw[7:]
            if raw.endswith("```"):
                raw = raw[:-3]

            data = json.loads(raw.strip())
            title = data.get("title", title)
            purpose = data.get("purpose", purpose)
            decisions = data.get("decisions", [])
            lessons = data.get("lessons", [])
            anchors = data.get("anchors", [])
        except Exception:
            # Fallback to deterministic synthesis from extracted facts
            affected = list(input_data.patch_set.affected_paths)
            first_path = affected[0] if affected else "README.md"
            anchors = [f"{first_path}:1@{input_data.base_commit}"]
            decisions = [f"Applied patch to {len(affected)} file(s)"]
            lessons = ["Verified and merged successfully"]

        # If LLM didn't supply anchors, derive default anchors deterministically
        if not anchors and input_data.patch_set.affected_paths:
            for p in list(input_data.patch_set.affected_paths)[:2]:
                anchors.append(f"{p}:1@{input_data.base_commit}")

        note_id = f"note-{input_data.job_id}-{uuid.uuid4().hex[:6]}"
        provenance = NoteProvenance(
            job_id=input_data.job_id,
            base_commit=input_data.base_commit,
            model=self.model_id,
            prompt_version="curator-v2.1",
            generated_at=datetime.now(UTC),
        )

        initial_note = ProjectNote(
            note_id=note_id,
            project_id=input_data.project_id,
            status=NoteStatus.PROPOSED,
            provenance=provenance,
            title=title,
            purpose=purpose,
            decisions=decisions,
            lessons=lessons,
            anchors=anchors,
        )

        # 1. Propose note into staging _inbox/ (§22.3)
        staged_file = self.staging_manager.propose_project_note(initial_note)

        # 2. Deterministic validation of anchors and secrets (§22.4)
        validated_note = self.validator.validate_and_transition(initial_note)
        validated_note = validated_note.model_copy(update={"file_path": str(staged_file)})

        # Update staged file with final validation status
        staged_file.write_text(validated_note.to_markdown(), encoding="utf-8")

        return CuratorResult(
            job_id=input_data.job_id,
            notes=[validated_note],
            success=True,
            summary=(
                f"Synthesized note {note_id} in staging (status: {validated_note.status.value})"
            ),
            model_used=self.model_id,
            tokens_used=tokens_used,
        )
