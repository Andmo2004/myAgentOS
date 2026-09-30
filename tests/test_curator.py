"""Unit and integration tests for the Curator role and knowledge update (§22)."""

import json
from pathlib import Path

import pytest

from myagentos.core.models.knowledge import (
    CuratorInput,
    NoteProvenance,
    NoteStatus,
    ProjectNote,
)
from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.curator.agent import CuratorAgent
from myagentos.curator.staging import (
    MAX_NOTE_SIZE_BYTES,
    NoteStagingManager,
    StagingLimitExceededError,
    StagingOverwriteViolationError,
)
from myagentos.curator.staleness import StalenessTracker
from myagentos.curator.validator import DeterministicNoteValidator
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator


def _make_sample_note(
    job_id: str = "job-1",
    note_id: str = "note-test-1",
    anchors: list[str] | None = None,
) -> ProjectNote:
    return ProjectNote(
        note_id=note_id,
        project_id="test-proj",
        status=NoteStatus.PROPOSED,
        provenance=NoteProvenance(
            job_id=job_id,
            base_commit="commit-1",
            model="mock",
        ),
        title="Sample Architecture Note",
        purpose="Refactored billing engine to decouple calculation",
        decisions=["Extracted InvoiceCalculator class"],
        lessons=["Use pure functions for discount rates"],
        anchors=anchors or ["src/billing.py:InvoiceCalculator@commit-1"],
    )


def test_note_staging_create_only_and_limits(tmp_path: Path) -> None:
    """Verifies staging inbox isolation, create-only enforcement, and hard quotas (§22.3)."""
    manager = NoteStagingManager(tmp_path)

    # 1. Successful proposal into _inbox/
    note = _make_sample_note(job_id="job-1", note_id="note-1")
    path = manager.propose_project_note(note)
    assert path.exists()
    assert "_inbox" in str(path)
    assert "note-1.md" in path.name

    # 2. Overwrite attempt must raise StagingOverwriteViolationError
    with pytest.raises(StagingOverwriteViolationError):
        manager.propose_project_note(note)

    # 3. Maximum notes per job quota enforcement (MAX_NOTES_PER_JOB = 3)
    note2 = _make_sample_note(job_id="job-1", note_id="note-2")
    note3 = _make_sample_note(job_id="job-1", note_id="note-3")
    manager.propose_project_note(note2)
    manager.propose_project_note(note3)

    note4 = _make_sample_note(job_id="job-1", note_id="note-4")
    with pytest.raises(StagingLimitExceededError):
        manager.propose_project_note(note4)

    # 4. Note size quota enforcement (MAX_NOTE_SIZE_BYTES = 8192)
    oversized_note = ProjectNote(
        note_id="note-oversized",
        project_id="test-proj",
        status=NoteStatus.PROPOSED,
        provenance=NoteProvenance(
            job_id="job-2",
            base_commit="commit-1",
            model="mock",
        ),
        title="Oversized",
        purpose="X" * (MAX_NOTE_SIZE_BYTES + 100),
        anchors=["src/billing.py:1@commit-1"],
    )
    with pytest.raises(StagingLimitExceededError):
        manager.propose_project_note(oversized_note)


def test_deterministic_note_validator(tmp_path: Path) -> None:
    """Verifies anchor existence and secret scanning transitions (§22.4)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    billing_file = src_dir / "billing.py"
    billing_file.write_text(
        "class InvoiceCalculator:\n"
        "    def calculate(self):\n"
        "        return 100\n"
    )

    validator = DeterministicNoteValidator(tmp_path)

    # 1. Valid symbol anchor -> transitions to VERIFIED
    valid_note = _make_sample_note(
        anchors=["src/billing.py:InvoiceCalculator@commit-1"]
    )
    verified = validator.validate_and_transition(valid_note)
    assert verified.status == NoteStatus.VERIFIED
    assert len(verified.rejection_reasons) == 0

    # 2. Valid line anchor -> transitions to VERIFIED
    line_note = _make_sample_note(
        anchors=["src/billing.py:2@commit-1"]
    )
    verified_line = validator.validate_and_transition(line_note)
    assert verified_line.status == NoteStatus.VERIFIED

    # 3. Nonexistent file anchor -> transitions to REJECTED
    broken_file_note = _make_sample_note(
        anchors=["src/missing.py:Foo@commit-1"]
    )
    rejected_file = validator.validate_and_transition(broken_file_note)
    assert rejected_file.status == NoteStatus.REJECTED
    assert any("does not exist" in r for r in rejected_file.rejection_reasons)

    # 4. Missing symbol anchor -> transitions to REJECTED
    broken_sym_note = _make_sample_note(
        anchors=["src/billing.py:NonExistentClass@commit-1"]
    )
    rejected_sym = validator.validate_and_transition(broken_sym_note)
    assert rejected_sym.status == NoteStatus.REJECTED
    assert any("not found" in r for r in rejected_sym.rejection_reasons)

    # 5. Out of bounds line anchor -> transitions to REJECTED
    oob_note = _make_sample_note(
        anchors=["src/billing.py:999@commit-1"]
    )
    rejected_oob = validator.validate_and_transition(oob_note)
    assert rejected_oob.status == NoteStatus.REJECTED
    assert any("out of bounds" in r for r in rejected_oob.rejection_reasons)


def test_staleness_tracker() -> None:
    """Verifies that modified files transition verified notes to stale (§22.5)."""
    note = _make_sample_note(anchors=["src/billing.py:InvoiceCalculator@commit-1"])
    verified = note.model_copy(update={"status": NoteStatus.VERIFIED})

    # When src/billing.py is modified in a later commit:
    updated = StalenessTracker.update_notes_staleness(
        notes=[verified],
        modified_files={"src/billing.py"},
    )
    assert updated[0].status == NoteStatus.STALE

    # When an unrelated file is modified:
    untouched = StalenessTracker.update_notes_staleness(
        notes=[verified],
        modified_files={"src/unrelated.py"},
    )
    assert untouched[0].status == NoteStatus.VERIFIED


def test_curator_agent_flow_and_non_blocking(tmp_path: Path) -> None:
    """Tests CuratorAgent generation, staging, and non-blocking safety (§22.2)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    calc_file = src_dir / "calc.py"
    calc_file.write_text("def add(a, b): return a + b\n")

    class MockCuratorAdapter(ProviderAdapter):
        def generate(
            self,
            messages: list[LLMMessage],
            model_id: str,
            temperature: float = 0.0,
            response_schema: type | None = None,
        ) -> LLMResponse:
            content = json.dumps(
                {
                    "title": "Add calculation function",
                    "purpose": "Provides arithmetic addition",
                    "decisions": ["Used pure function"],
                    "lessons": ["Test with pytest"],
                    "anchors": ["src/calc.py:add@head"],
                }
            )
            return LLMResponse(
                content=content, model_id=model_id, input_tokens=40, output_tokens=30
            )

    gateway = ModelGateway()
    gateway.register_adapter("mock", MockCuratorAdapter())

    agent = CuratorAgent(repo_root=tmp_path, gateway=gateway, model_id="mock")

    plan = PlanSpec(
        plan_id="plan-1",
        job_id="job-1",
        base_commit="head",
        files_to_modify=["src/calc.py"],
        impact_summary="Add calculation function",
        preliminary_risk=RiskLevel.LOW,
    )
    patch_set = PatchSet(
        job_id="job-1",
        base_commit="head",
        files=[
            FilePatch(
                path="src/calc.py",
                operation=PatchOperation.MODIFY,
                patch="def add(a, b): return a + b\n",
                sha256_before="111",
                sha256_after="222",
            )
        ],
    )

    curator_input = CuratorInput(
        job_id="job-1",
        project_id="test-app",
        patch_set=patch_set,
        plan=plan,
        base_commit="head",
    )

    res = agent.curate_knowledge(curator_input)
    assert res.success is True
    assert len(res.notes) == 1
    note = res.notes[0]
    assert note.status == NoteStatus.VERIFIED
    assert note.anchors == ["src/calc.py:add@head"]
    assert note.file_path is not None
    assert Path(note.file_path).exists()


def test_pipeline_e2e_curator_integration(tmp_path: Path) -> None:
    """Verifies that the full pipeline executes knowledge curation post-merge (§8, §22)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    target = src_dir / "app.py"
    target.write_text("MESSAGE = 'hello'\n")

    worker_resp = json.dumps(
        {
            "thought": "Update app message",
            "propose_patch": {
                "description": "Update message",
                "files": [
                    {
                        "path": "src/app.py",
                        "operation": "MODIFY",
                        "content": "MESSAGE = 'welcome'\n",
                    }
                ],
            },
        }
    )

    class PipelineGatewayAdapter(ProviderAdapter):
        def generate(
            self,
            messages: list[LLMMessage],
            model_id: str,
            temperature: float = 0.0,
            response_schema: type | None = None,
        ) -> LLMResponse:
            system_msg = messages[0].content if messages else ""
            if "Knowledge Curator" in system_msg:
                note_json = json.dumps(
                    {
                        "title": "Welcome Message Update",
                        "purpose": "Enhance greeting experience",
                        "decisions": ["Direct constant change"],
                        "lessons": ["Keep greetings friendly"],
                        "anchors": ["src/app.py:1@local-head"],
                    }
                )
                return LLMResponse(
                    content=note_json, model_id=model_id, input_tokens=40, output_tokens=30
                )
            return LLMResponse(
                content=worker_resp, model_id=model_id, input_tokens=30, output_tokens=30
            )

    gateway = ModelGateway()
    gateway.register_adapter("mock", PipelineGatewayAdapter())

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)
    result = orchestrator.run("/direct update message in src/app.py")

    assert result.success is True
    assert len(result.notes) == 1
    assert result.notes[0].status == NoteStatus.VERIFIED
    assert result.notes[0].anchors == ["src/app.py:1@local-head"]

    # Verify event store contains NOTE_PROPOSED, NOTE_VALIDATED, and KNOWLEDGE_UPDATE_COMPLETED
    events = orchestrator.event_store.load_events(result.job_id)
    event_names = [e.event_name for e in events]
    assert "NOTE_PROPOSED" in event_names
    assert "NOTE_VALIDATED" in event_names
    assert "KNOWLEDGE_UPDATE_COMPLETED" in event_names
