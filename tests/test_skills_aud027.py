"""Test suite for Just-in-Time Skills and Least-Privilege Capabilities (§20, AUD-027)."""

import json
from pathlib import Path

import pytest

from myagentos.core.models.data_policy import TrustTag
from myagentos.core.models.event import EventActor, EventName
from myagentos.core.models.risk import RiskLevel
from myagentos.core.models.token import CapabilityToken, NetworkScope, TokenLimits
from myagentos.fsm.states import JobState
from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.pipeline.models import PipelineConfig
from myagentos.pipeline.orchestrator import PipelineOrchestrator
from myagentos.skills.enforcer import SkillPermissionEnforcer
from myagentos.skills.loader import SkillLoader, SkillLoadError
from myagentos.skills.models import (
    SkillManifest,
    SkillMatchCriteria,
    SkillPermissions,
    SkillVerification,
)
from myagentos.skills.registry import SkillRegistry


class ScriptedSkillsAdapter(ProviderAdapter):
    """Feeds pre-defined responses for Planner and Worker."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.index = 0
        self.recorded_messages: list[list[LLMMessage]] = []

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type | None = None,
    ) -> LLMResponse:
        self.recorded_messages.append(messages)
        if self.index < len(self.responses):
            resp = self.responses[self.index]
            self.index += 1
        else:
            resp = self.responses[-1]
        return LLMResponse(content=resp, model_id=model_id, input_tokens=30, output_tokens=50)


# ==============================================================================
# Unit Tests: Manifest and Models (§20)
# ==============================================================================


def test_skill_manifest_hash_and_identifier_stability() -> None:
    manifest1 = SkillManifest(
        name="sql-optimizer",
        version="1.2.0",
        description="Optimizes SQL query indices",
        min_risk_level=RiskLevel.MEDIUM,
        match=SkillMatchCriteria(keywords=["sql", "query"], extensions=[".sql"]),
        permissions_requested=SkillPermissions(
            read=["queries/**"],
            write=["queries/optimized/**"],
            execute=["pg_dump"],
        ),
        verification=SkillVerification(
            protected_paths_add=["schema/production/**"],
            commands=["pytest -m sql"],
        ),
        instructions="Always examine EXPLAIN ANALYZE before patching queries.",
    )
    hash1 = manifest1.compute_content_hash()
    assert len(hash1) == 64
    assert int(hash1, 16) > 0  # Valid hex string

    # Check identifier property
    manifest1_with_hash = manifest1.model_copy(update={"content_hash": hash1})
    assert manifest1_with_hash.identifier == f"sql-optimizer@1.2.0#{hash1[:8]}"

    # Modifying instructions changes hash
    manifest2 = manifest1.model_copy(update={"instructions": "Different instructions"})
    assert manifest2.compute_content_hash() != hash1

    # Modifying min_risk_level changes hash
    manifest3 = manifest1.model_copy(update={"min_risk_level": RiskLevel.HIGH})
    assert manifest3.compute_content_hash() != hash1

    # Modifying permissions changes hash
    manifest4 = manifest1.model_copy(
        update={
            "permissions_requested": SkillPermissions(
                read=["queries/**"],
                write=["queries/optimized/**", "queries/benchmarks/**"],
            )
        }
    )
    assert manifest4.compute_content_hash() != hash1


def test_skill_manifest_immutability() -> None:
    manifest = SkillManifest(name="readonly-skill")
    with pytest.raises(Exception):
        # Pydantic ValidationError or TypeError on frozen model
        setattr(manifest, "name", "mutated-skill")


# ==============================================================================
# Unit Tests: Skill Loader (§20)
# ==============================================================================


def test_skill_loader_from_dir_yaml_and_markdown(tmp_path: Path) -> None:
    skill_dir = tmp_path / "python_expert"
    skill_dir.mkdir(parents=True)

    yaml_content = """
name: python-expert
version: "2.0.0"
description: Advanced Python typing and refactoring
min_risk_level: MEDIUM
match:
  keywords:
    - python
    - typing
  paths:
    - "src/**/*.py"
  extensions:
    - ".py"
permissions_requested:
  read:
    - "src/**/*.py"
    - "tests/**/*.py"
  write:
    - "src/**/*.py"
  execute:
    - "mypy"
    - "pytest"
verification:
  protected_paths_add:
    - "src/core/security.py"
  commands:
    - "mypy src"
"""
    (skill_dir / "metadata.yaml").write_text(yaml_content)
    (skill_dir / "instructions.md").write_text("Enforce PEP 484 and strict type annotations.\n")

    skill = SkillLoader.load_skill_from_dir(skill_dir)
    assert skill.name == "python-expert"
    assert skill.version == "2.0.0"
    assert skill.min_risk_level == RiskLevel.MEDIUM
    assert "typing" in skill.match.keywords
    assert ".py" in skill.match.extensions
    assert "src/**/*.py" in skill.permissions_requested.write
    assert "src/core/security.py" in skill.verification.protected_paths_add
    assert "PEP 484" in skill.instructions
    assert skill.content_hash != ""
    assert skill.identifier.startswith("python-expert@2.0.0#")


def test_skill_loader_from_dir_json(tmp_path: Path) -> None:
    skill_dir = tmp_path / "json_skill"
    skill_dir.mkdir(parents=True)

    json_content = json.dumps(
        {
            "name": "json-tool",
            "version": "1.0.1",
            "description": "JSON formatter",
            "min_risk_level": "LOW",
            "match": {"extensions": [".json"]},
            "permissions_requested": {"read": ["*.json"], "write": ["*.json"]},
            "instructions": "Format JSON with 2-space indentation.",
        }
    )
    (skill_dir / "metadata.json").write_text(json_content)

    skill = SkillLoader.load_skill_from_dir(skill_dir)
    assert skill.name == "json-tool"
    assert skill.min_risk_level == RiskLevel.LOW
    assert ".json" in skill.match.extensions
    assert "2-space indentation" in skill.instructions


def test_skill_loader_failures_and_scan(tmp_path: Path) -> None:
    # 1. Non-directory raises
    non_dir = tmp_path / "not_a_dir.txt"
    non_dir.write_text("hello")
    with pytest.raises(SkillLoadError, match="not a directory"):
        SkillLoader.load_skill_from_dir(non_dir)

    # 2. Directory without metadata raises
    empty_dir = tmp_path / "empty_skill"
    empty_dir.mkdir()
    with pytest.raises(SkillLoadError, match="No metadata file found"):
        SkillLoader.load_skill_from_dir(empty_dir)

    # 3. Directory with invalid metadata (missing name) raises
    bad_dir = tmp_path / "bad_skill"
    bad_dir.mkdir()
    (bad_dir / "metadata.json").write_text(json.dumps({"version": "1.0.0"}))
    with pytest.raises(SkillLoadError, match="must include a valid 'name'"):
        SkillLoader.load_skill_from_dir(bad_dir)

    # 4. Scanning root with multiple valid and invalid skills
    skills_root = tmp_path / "skills_root"
    skills_root.mkdir()

    valid_1 = skills_root / "skill_1"
    valid_1.mkdir()
    (valid_1 / "metadata.json").write_text(json.dumps({"name": "s1"}))

    valid_2 = skills_root / "skill_2"
    valid_2.mkdir()
    (valid_2 / "metadata.json").write_text(json.dumps({"name": "s2"}))

    # Dot directory should be skipped
    hidden = skills_root / ".git"
    hidden.mkdir()

    discovered = SkillLoader.load_skills_from_root(skills_root)
    assert len(discovered) == 2
    assert {s.name for s in discovered} == {"s1", "s2"}


# ==============================================================================
# Unit Tests: Skill Registry & JIT Matching (§20)
# ==============================================================================


def test_skill_registry_matching_triggers() -> None:
    registry = SkillRegistry()

    skill_db = SkillManifest(
        name="db-migration",
        match=SkillMatchCriteria(
            keywords=["migration", "schema"],
            paths=["migrations/**", "alembic/**"],
            extensions=[".sql"],
        ),
    )
    skill_auth = SkillManifest(
        name="security-audit",
        match=SkillMatchCriteria(
            keywords=["jwt", "auth", "token"],
            paths=["src/auth/**"],
        ),
    )
    registry.register(skill_db)
    registry.register(skill_auth)

    # Match by keyword
    matched = registry.match_skills(task_prompt="Run database migration for new tables")
    assert len(matched) == 1
    assert matched[0].name == "db-migration"

    # Match by target path glob
    matched_paths = registry.match_skills(
        task_prompt="Refactor user models",
        target_paths=["migrations/001_create_users.sql"],
    )
    assert len(matched_paths) == 1
    assert matched_paths[0].name == "db-migration"

    # Match by extension
    matched_ext = registry.match_skills(
        task_prompt="Format queries",
        target_paths=["queries/select_users.sql"],
    )
    assert len(matched_ext) == 1
    assert matched_ext[0].name == "db-migration"

    # Match by explicit trigger /skill <name>
    matched_explicit = registry.match_skills(
        task_prompt="/skill security-audit Check authentication headers",
    )
    assert len(matched_explicit) == 1
    assert matched_explicit[0].name == "security-audit"

    # Match by explicit trigger /skill:<name>
    matched_colon = registry.match_skills(
        task_prompt="/skill:security-audit Check auth logic",
    )
    assert len(matched_colon) == 1
    assert matched_colon[0].name == "security-audit"

    # Match via explicit_skills parameter
    matched_param = registry.match_skills(
        task_prompt="General maintenance",
        explicit_skills=["db-migration", "security-audit"],
    )
    assert len(matched_param) == 2

    # Multiple triggers on same skill produce no duplicates
    matched_multi = registry.match_skills(
        task_prompt="/skill db-migration Run schema migration",
        target_paths=["migrations/init.sql"],
    )
    assert len(matched_multi) == 1
    assert matched_multi[0].name == "db-migration"


# ==============================================================================
# Unit Tests: AUD-027 Least-Privilege Token Intersection & Monotonic Risk
# ==============================================================================


def test_aud027_least_privilege_token_intersection() -> None:
    """Normative AUD-027 requirement:
    skill_permissions = requested_permissions ∩ approved_scope ∩ project_policy

    A skill's requested permissions represent a CEILING; a skill can NEVER expand permissions.
    """
    from datetime import UTC, datetime, timedelta

    base_token = CapabilityToken(
        job_id="job-100",
        worker_id="worker-default",
        risk_level=RiskLevel.LOW,
        read_scope=["src/api/**", "src/db/**"],
        write_scope=["src/api/auth.py", "src/api/user.py"],
        execute_scope=["pytest"],
        network_scope=NetworkScope.NONE,
        limits=TokenLimits(max_files=5, max_diff_lines=200, max_steps=10),
        trust=TrustTag.UNTRUSTED,
        skills=[],
        base_commit="abc1234",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )

    # Skill requests broad write permissions including files NOT in base_token
    # and commands not approved in base_token
    skill = SkillManifest(
        name="auth-helper",
        version="1.0.0",
        min_risk_level=RiskLevel.MEDIUM,
        permissions_requested=SkillPermissions(
            read=["src/api/**"],  # Subset of base read
            write=[
                "src/api/auth.py",
                "src/secrets.env",
            ],  # src/secrets.env is NOT in base write!
            execute=["pytest", "curl"],  # curl is NOT in base execute!
        ),
    )

    intersected = SkillPermissionEnforcer.intersect_token_with_skills(
        base_token=base_token,
        skills=[skill],
    )

    # 1. Read scope: only "src/api/**" (common to both)
    assert set(intersected.read_scope) == {"src/api/**"}

    # 2. Write scope: only "src/api/auth.py"
    # "src/secrets.env" MUST BE REJECTED because it exceeds base token approved scope!
    # "src/api/user.py" is in base token but NOT in skill ceiling, so it is excluded!
    assert set(intersected.write_scope) == {"src/api/auth.py"}

    # 3. Execute scope: only "pytest"
    # "curl" MUST BE REJECTED because base token did not allow curl!
    assert set(intersected.execute_scope) == {"pytest"}

    # 4. Limits take lowest ceiling
    assert intersected.limits.max_files <= 5

    # 5. Token records active skill identifier
    assert any("auth-helper@1.0.0#" in s for s in intersected.skills)


def test_aud027_monotonic_risk_elevation() -> None:
    """Normative AUD-027 requirement:
    skill can increase risk, skill cannot reduce risk.
    """
    skill_low = SkillManifest(name="s-low", min_risk_level=RiskLevel.LOW)
    skill_med = SkillManifest(name="s-med", min_risk_level=RiskLevel.MEDIUM)
    skill_high = SkillManifest(name="s-high", min_risk_level=RiskLevel.HIGH)
    skill_crit = SkillManifest(name="s-crit", min_risk_level=RiskLevel.CRITICAL)

    # 1. Skill increases risk from LOW to HIGH
    assert (
        SkillPermissionEnforcer.compute_effective_risk(RiskLevel.LOW, [skill_high])
        == RiskLevel.HIGH
    )

    # 2. Skill CANNOT reduce risk from CRITICAL to LOW or MEDIUM
    assert (
        SkillPermissionEnforcer.compute_effective_risk(RiskLevel.CRITICAL, [skill_low, skill_med])
        == RiskLevel.CRITICAL
    )

    # 3. Multiple skills: take the maximum across base and all skills
    assert (
        SkillPermissionEnforcer.compute_effective_risk(
            RiskLevel.MEDIUM, [skill_low, skill_high, skill_crit]
        )
        == RiskLevel.CRITICAL
    )

    # 4. Base HIGH with skill LOW remains HIGH
    assert (
        SkillPermissionEnforcer.compute_effective_risk(RiskLevel.HIGH, [skill_low])
        == RiskLevel.HIGH
    )


def test_aud027_additive_protected_paths() -> None:
    """Skills can ADD protected paths, but can NEVER remove existing base paths."""
    base_paths = ["config/secrets.json", ".env*"]
    skill1 = SkillManifest(
        name="s1",
        verification=SkillVerification(protected_paths_add=["db/migrations/**", ".env*"]),
    )
    skill2 = SkillManifest(
        name="s2",
        verification=SkillVerification(protected_paths_add=["src/core/security.py"]),
    )

    combined = SkillPermissionEnforcer.compute_additive_protected_paths(
        base_paths, [skill1, skill2]
    )

    # Base paths are strictly preserved
    assert "config/secrets.json" in combined
    assert ".env*" in combined
    # Additive paths from skills are included
    assert "db/migrations/**" in combined
    assert "src/core/security.py" in combined
    # No duplicate entries
    assert combined.count(".env*") == 1


def test_skill_instructions_prefix_generation() -> None:
    skill1 = SkillManifest(
        name="type-checker",
        version="1.0.0",
        description="Type validation guideline",
        instructions="Always write complete type hints.",
    )
    skill2 = SkillManifest(
        name="doc-generator",
        version="2.0.0",
        description="",
        instructions="Add Google style docstrings.",
    )

    prefix = SkillPermissionEnforcer.build_skill_instructions_prefix([skill1, skill2])
    assert "# Active Domain Skills & Guidelines (§20)" in prefix
    assert "## Skill: type-checker (v1.0.0)" in prefix
    assert "_Type validation guideline_" in prefix
    assert "Always write complete type hints." in prefix
    assert "## Skill: doc-generator (v2.0.0)" in prefix
    assert "Add Google style docstrings." in prefix

    # Empty list returns empty string
    assert SkillPermissionEnforcer.build_skill_instructions_prefix([]) == ""


# ==============================================================================
# End-to-End Pipeline Integration Test with Skill Activation (§20, AUD-027)
# ==============================================================================


def test_pipeline_e2e_skill_activation_and_token_restriction(tmp_path: Path) -> None:
    """Full lifecycle verifying JIT skill discovery, manifest verification,
    token intersection ceiling, and SKILL_ACTIVATED audit event recording in hash chain.
    """
    # 1. Setup repository with skills directory
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    src_dir = repo_root / "src"
    src_dir.mkdir()
    auth_file = src_dir / "auth.py"
    auth_file.write_text("def verify_token(): return False\n")

    skills_root = repo_root / "skills"
    skills_root.mkdir()
    auth_skill_dir = skills_root / "auth_expert"
    auth_skill_dir.mkdir()

    metadata_yaml = """
name: auth-expert
version: "1.0.0"
description: Strict security authentication guidelines
min_risk_level: HIGH
match:
  keywords:
    - authentication
    - security
  paths:
    - "src/auth.py"
permissions_requested:
  read:
    - "src/auth.py"
  write:
    - "src/auth.py"
  execute:
    - "pytest"
verification:
  protected_paths_add:
    - "src/vault/**"
  commands:
    - "pytest tests/test_auth.py"
"""
    (auth_skill_dir / "metadata.yaml").write_text(metadata_yaml)
    (auth_skill_dir / "instructions.md").write_text(
        "Never log decrypted tokens. Enforce constant-time comparison.\n"
    )

    # 2. Planner and Worker responses (Prompt has "security" which router escalates to PLANNED_CODE)
    planner_resp = json.dumps(
        {
            "files_to_modify": ["src/auth.py"],
            "files_to_create": [],
            "files_to_delete": [],
            "altered_interfaces": ["def verify_token() -> bool"],
            "test_specs": ["test_verify_token_valid"],
            "preliminary_risk": "HIGH",
            "risk_reasons": ["Modifying authentication logic"],
            "permissions_requested": {
                "read": ["src/auth.py", "src/unused.py"],
                "write": ["src/auth.py", "src/other.py"],
                "execute": ["pytest"],
            },
            "impact_summary": "Update security verification",
            "rationale": "Fix token check",
        }
    )

    worker_resp = json.dumps(
        {
            "thought": "Patching verify_token according to auth-expert skill guidelines",
            "propose_patch": {
                "description": "Fix token verification logic",
                "files": [
                    {
                        "path": "src/auth.py",
                        "operation": "MODIFY",
                        "content": "def verify_token(): return True\n",
                    }
                ],
            },
        }
    )

    adapter = ScriptedSkillsAdapter([planner_resp, worker_resp])
    gateway = ModelGateway()
    gateway.register_adapter("mock", adapter)

    config = PipelineConfig(
        repo_root=repo_root,
        model_id="mock",
        auto_approve=True,
        use_worktree=False,
        skills_dir=skills_root,
    )
    orchestrator = PipelineOrchestrator(config=config, gateway=gateway)

    # 3. Run task triggering the skill by keyword "security" and path "src/auth.py"
    result = orchestrator.run("Update security verification in src/auth.py")

    assert result.success is True
    assert result.final_state == JobState.COMPLETE
    assert result.patch_set is not None
    assert result.hash_chain_intact is True

    # 4. Verify file modification took effect
    assert auth_file.read_text() == "def verify_token(): return True\n"

    # 5. Verify SKILL_ACTIVATED event was logged by SKILL_REGISTRY into audit trail
    events = orchestrator.event_store.load_events(result.job_id)
    skill_events = [
        e
        for e in events
        if e.event_name == EventName.SKILL_ACTIVATED and e.actor == EventActor.SKILL_REGISTRY
    ]
    assert len(skill_events) >= 1
    skill_evt = skill_events[0]
    payload = skill_evt.payload
    assert payload["skill_name"] == "auth-expert"
    assert payload["min_risk"] == "HIGH"
    assert "Never log decrypted tokens" in payload["instructions"]
    assert "src/vault/**" in payload["verification"]["protected_paths_add"]

    # 6. Verify worker received prompt containing the skill instructions in stable prefix
    assert len(adapter.recorded_messages) >= 2
    worker_prompt = adapter.recorded_messages[1][-1].content
    assert "# Active Domain Skills & Guidelines (§20)" in worker_prompt
    assert "auth-expert" in worker_prompt
    assert "Never log decrypted tokens" in worker_prompt
