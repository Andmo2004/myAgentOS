"""AUD-018: Secret fixtures and full redaction pipeline validation across all subsystems.

Verifies: no secret -> prompt -> logs -> events -> reports -> model request -> knowledge notes.
Follows §18, §22.4, and AUD-018.
"""

import json
from pathlib import Path

from myagentos.context.compiler import ContextCompiler
from myagentos.core.models.knowledge import NoteStatus
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskLevel
from myagentos.curator.validator import DeterministicNoteValidator
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator
from myagentos.policy.engine import PolicyEngine

SAMPLE_API_KEY = "sk-live-9876543210abcdef9876543210abcdef"
SAMPLE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
SAMPLE_GH_PAT = "ghp_123456789012345678901234567890123456"
SAMPLE_PRIVATE_KEY = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...\n"
)
SAMPLE_ENV_PASSWORD = "database_super_secret_password_2026!"


def _setup_synthetic_secret_repo(repo_dir: Path) -> dict[str, Path]:
    """Populates a synthetic repository containing common secret types (AUD-018)."""
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # 1. Source file with hardcoded API key
    service_file = src_dir / "service.py"
    service_file.write_text(f"OPENAI_KEY = '{SAMPLE_API_KEY}'\nAWS_KEY = '{SAMPLE_AWS_KEY}'\n")

    # 2. .env file with secrets
    env_file = repo_dir / ".env"
    env_file.write_text(f"DB_PASSWORD='{SAMPLE_ENV_PASSWORD}'\nTOKEN='{SAMPLE_GH_PAT}'\n")

    # 3. Private key file
    key_file = repo_dir / "id_rsa"
    key_file.write_text(SAMPLE_PRIVATE_KEY)

    # 4. Standard public file
    readme = repo_dir / "README.md"
    readme.write_text("# Synthetic Secret Test Repo\nClean public documentation.\n")

    return {
        "service": service_file,
        "env": env_file,
        "key": key_file,
        "readme": readme,
    }


def test_aud018_secret_files_pruned_from_plan_context(tmp_path: Path) -> None:
    """Verifies .env, id_rsa, and secret files are pruned from repository maps (AUD-018)."""
    _setup_synthetic_secret_repo(tmp_path)

    compiler = ContextCompiler(repo_root=tmp_path)
    plan_ctx = compiler.compile_plan_context(
        job_id="job-sec-1",
        prompt="Review project structure",
    )

    prompt_text = f"{plan_ctx.stable_prefix}\n{plan_ctx.variable_suffix}"

    # Secret files must NEVER appear in the planner prompt or repository tree
    assert ".env" not in prompt_text
    assert "id_rsa" not in prompt_text
    assert SAMPLE_API_KEY not in prompt_text
    assert SAMPLE_ENV_PASSWORD not in prompt_text
    assert SAMPLE_GH_PAT not in prompt_text


def test_aud018_secret_content_redacted_in_worker_context(tmp_path: Path) -> None:
    """Verifies that secret content is redacted with [REDACTED: SECRET DETECTED BY POLICY §18]."""
    _setup_synthetic_secret_repo(tmp_path)

    compiler = ContextCompiler(repo_root=tmp_path)
    policy_engine = PolicyEngine()

    plan = PlanSpec(
        plan_id="plan-sec-2",
        job_id="job-sec-2",
        base_commit="head",
        files_to_modify=["src/service.py"],
        preliminary_risk=RiskLevel.HIGH,
        permissions_requested={
            "read": ["src/service.py"],
            "write": ["src/service.py"],
            "execute": [],
        },
    )
    token = policy_engine.issue_capability_token(
        job_id="job-sec-2",
        worker_id="worker-sec-2",
        plan=plan,
        risk_level=RiskLevel.HIGH,
    )

    worker_ctx = compiler.compile_worker_context(
        job_id="job-sec-2",
        prompt="Update service",
        plan=plan,
        token=token,
    )

    prompt_text = f"{worker_ctx.stable_prefix}\n{worker_ctx.variable_suffix}"

    # The secret content must be redacted
    assert SAMPLE_API_KEY not in prompt_text
    assert SAMPLE_AWS_KEY not in prompt_text
    assert "[REDACTED: SECRET DETECTED BY POLICY §18]" in prompt_text


def test_aud018_curator_validator_rejects_secrets_in_notes(tmp_path: Path) -> None:
    """Verifies that Curator rejects notes containing credentials or tokens (AUD-018, §22.4)."""
    _setup_synthetic_secret_repo(tmp_path)
    validator = DeterministicNoteValidator(tmp_path)

    from myagentos.core.models.knowledge import NoteProvenance, ProjectNote

    # 1. Attempt to store API key in purpose
    leak_note = ProjectNote(
        note_id="note-leak-1",
        project_id="test",
        status=NoteStatus.PROPOSED,
        provenance=NoteProvenance(job_id="job-sec-3", base_commit="head", model="mock"),
        title="Note with leaked API key",
        purpose=f"Configured service with key {SAMPLE_API_KEY}",
        anchors=["src/service.py:1@head"],
    )
    validated = validator.validate_and_transition(leak_note)
    assert validated.status == NoteStatus.REJECTED
    assert any("Detected secret pattern" in r for r in validated.rejection_reasons)

    # 2. Attempt to store Bearer token in decisions
    bearer_note = ProjectNote(
        note_id="note-leak-2",
        project_id="test",
        status=NoteStatus.PROPOSED,
        provenance=NoteProvenance(job_id="job-sec-4", base_commit="head", model="mock"),
        title="Note with bearer token",
        purpose="Update authentication",
        decisions=["Used token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"],
        anchors=["src/service.py:1@head"],
    )
    validated_bearer = validator.validate_and_transition(bearer_note)
    assert validated_bearer.status == NoteStatus.REJECTED
    assert any("Detected potential credential" in r for r in validated_bearer.rejection_reasons)


def test_aud018_e2e_pipeline_zero_secrets_leakage(tmp_path: Path) -> None:
    """AUD-018 full chain: no secret -> prompt -> logs -> events -> reports -> model request."""
    _setup_synthetic_secret_repo(tmp_path)

    captured_requests: list[str] = []

    class SecretAuditGatewayAdapter(ProviderAdapter):
        def generate(
            self,
            messages: list[LLMMessage],
            model_id: str,
            temperature: float = 0.0,
            response_schema: type | None = None,
        ) -> LLMResponse:
            for m in messages:
                captured_requests.append(m.content)

            system_msg = messages[0].content if messages else ""
            if "Knowledge Curator" in system_msg:
                return LLMResponse(
                    content=json.dumps(
                        {
                            "title": "Clean Note",
                            "purpose": "Decoupled service configuration",
                            "decisions": ["Used environment variable"],
                            "lessons": ["Never hardcode keys"],
                            "anchors": ["src/service.py:1@local-head"],
                        }
                    ),
                    model_id=model_id,
                    input_tokens=50,
                    output_tokens=30,
                )

            worker_resp = json.dumps(
                {
                    "thought": "Update service safely using env var",
                    "propose_patch": {
                        "description": "Refactor to use os.environ",
                        "files": [
                            {
                                "path": "src/service.py",
                                "operation": "MODIFY",
                                "content": "import os\nOPENAI_KEY = os.getenv('OPENAI_KEY')\n",
                            }
                        ],
                    },
                }
            )
            return LLMResponse(
                content=worker_resp, model_id=model_id, input_tokens=50, output_tokens=30
            )

    gateway = ModelGateway()
    gateway.register_adapter("mock", SecretAuditGatewayAdapter())

    config = PipelineConfig(
        repo_root=tmp_path,
        model_id="mock",
        auto_approve=True,
        use_worktree=True,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)
    result = orchestrator.run("/direct update service in src/service.py")

    assert result.success is True

    # Check 1: Model request messages must NOT contain synthetic secrets
    for req_text in captured_requests:
        assert SAMPLE_API_KEY not in req_text
        assert SAMPLE_AWS_KEY not in req_text
        assert SAMPLE_GH_PAT not in req_text
        assert SAMPLE_ENV_PASSWORD not in req_text
        assert SAMPLE_PRIVATE_KEY not in req_text

    # Check 2: Events in EventStore must NOT contain synthetic secrets
    events = orchestrator.event_store.load_events(result.job_id)
    events_dump = json.dumps([e.model_dump(mode="json") for e in events])
    assert SAMPLE_API_KEY not in events_dump
    assert SAMPLE_AWS_KEY not in events_dump
    assert SAMPLE_GH_PAT not in events_dump
    assert SAMPLE_ENV_PASSWORD not in events_dump
    assert SAMPLE_PRIVATE_KEY not in events_dump

    # Check 3: Final report (PipelineResult) must NOT contain synthetic secrets
    report_dump = json.dumps(result.model_dump(mode="json"))
    assert SAMPLE_API_KEY not in report_dump
    assert SAMPLE_AWS_KEY not in report_dump
    assert SAMPLE_GH_PAT not in report_dump
    assert SAMPLE_ENV_PASSWORD not in report_dump
    assert SAMPLE_PRIVATE_KEY not in report_dump

    # Check 4: Staged knowledge notes in _inbox/ must NOT contain synthetic secrets
    inbox_notes = list((tmp_path / ".myagentos" / "memory" / "_inbox").glob("**/*.md"))
    for note_path in inbox_notes:
        note_content = note_path.read_text(encoding="utf-8")
        assert SAMPLE_API_KEY not in note_content
        assert SAMPLE_AWS_KEY not in note_content
        assert SAMPLE_GH_PAT not in note_content
        assert SAMPLE_ENV_PASSWORD not in note_content
        assert SAMPLE_PRIVATE_KEY not in note_content
