"""Domain models for Project Continuation Audit (PCA).

Implements closed taxonomies and contracts for repository snapshotting,
deterministic structural discovery, finding classification, baseline reporting,
and continuation context synthesis.
"""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FindingCode(StrEnum):
    """Closed enumeration of repository defect and anomaly codes (§13.2).

    Completely decoupled from system-level FailureCode (§14 of v2.1).
    """

    # Build & Diagnostics
    BUILD_FAILURE = "BUILD_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    TYPECHECK_FAILURE = "TYPECHECK_FAILURE"
    LINT_FAILURE = "LINT_FAILURE"

    # Imports & Symbols
    BROKEN_IMPORT = "BROKEN_IMPORT"
    MISSING_SYMBOL = "MISSING_SYMBOL"
    DEPENDENCY_CONFLICT = "DEPENDENCY_CONFLICT"
    DEPENDENCY_OUTDATED = "DEPENDENCY_OUTDATED"
    LOCKFILE_DRIFT = "LOCKFILE_DRIFT"

    # Configuration & Docs
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    DOC_DRIFT = "DOC_DRIFT"
    ARCHITECTURE_DRIFT = "ARCHITECTURE_DRIFT"

    # Security
    SECURITY_EXPOSURE = "SECURITY_EXPOSURE"
    SECRET_DETECTED = "SECRET_DETECTED"
    UNSAFE_DEFAULT = "UNSAFE_DEFAULT"

    # Code Health
    DEAD_CODE = "DEAD_CODE"
    DUPLICATED_LOGIC = "DUPLICATED_LOGIC"
    MISSING_TEST_COVERAGE_SIGNAL = "MISSING_TEST_COVERAGE_SIGNAL"

    # Git & Artifacts
    GIT_STATE_DIRTY = "GIT_STATE_DIRTY"
    UNCOMMITTED_CHANGE = "UNCOMMITTED_CHANGE"
    STALE_GENERATED_ARTIFACT = "STALE_GENERATED_ARTIFACT"

    # General
    TODO_ACCUMULATION = "TODO_ACCUMULATION"
    OBSOLETE_CONFIG = "OBSOLETE_CONFIG"
    UNCOVERED_ENTRYPOINT = "UNCOVERED_ENTRYPOINT"
    UNREPRODUCIBLE_BASELINE = "UNREPRODUCIBLE_BASELINE"

    UNKNOWN = "UNKNOWN"


class FindingSeverity(StrEnum):
    """Severity levels for findings detected in the audited project (§14).

    Describes the severity of the discovered condition, not the RiskLevel
    of a proposed future modification.
    """

    BLOCKER = "BLOCKER"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(StrEnum):
    """Lifecycle status of a finding (§40)."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    WONT_FIX = "WONT_FIX"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class EvidenceTier(StrEnum):
    """Epistemological tier of an evidence claim (§15)."""

    OBSERVED = "OBSERVED"  # Directly observed output from a tool/execution
    DERIVED = "DERIVED"  # Deterministic deduction from observed facts
    INFERRED = "INFERRED"  # Synthesized interpretation by the continuity analyst
    PROPOSED = "PROPOSED"  # Suggested follow-up or remediation
    UNKNOWN = "UNKNOWN"  # Explicitly unestablished or unverifiable


class DiagnosticType(StrEnum):
    """Types of project baseline checks (§10, §12)."""

    COMPILE = "COMPILE"
    TYPECHECK = "TYPECHECK"
    LINT = "LINT"
    UNIT_TEST = "UNIT_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    BUILD = "BUILD"
    SECURITY_SCAN = "SECURITY_SCAN"
    CUSTOM = "CUSTOM"


class ContinuationFreshnessState(StrEnum):
    """Freshness states for continuation contexts (§24)."""

    VALID = "VALID"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class EvidenceItem(BaseModel):
    """Concrete evidence backing an observation or finding (§13.1, §15)."""

    model_config = ConfigDict(frozen=True)

    kind: EvidenceTier = EvidenceTier.OBSERVED
    source: str
    command: str | None = None
    anchor: str | None = None
    observed_value: str | None = None
    expected_value: str | None = None
    details: dict[str, str] = Field(default_factory=dict)


class ProposedFindingAction(BaseModel):
    """Deterministic remediation or investigation action for a finding (§13.1)."""

    model_config = ConfigDict(frozen=True)

    id: str
    description: str
    prerequisites: list[str] = Field(default_factory=list)
    validation: str | None = None


class Finding(BaseModel):
    """A verified issue, drift, or signal detected in the repository (§13.1)."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    code: FindingCode
    severity: FindingSeverity
    status: FindingStatus = FindingStatus.OPEN
    title: str
    summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    impact: str | None = None
    reproducibility: str = "HIGH"  # HIGH, LIMITED, UNKNOWN
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    introduced_in: str | None = None
    last_verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    proposed_actions: list[ProposedFindingAction] = Field(default_factory=list)


ProjectFinding = Finding


class WorkingTreeState(BaseModel):
    """State of the git working tree at snapshot time (§7)."""

    model_config = ConfigDict(frozen=True)

    clean: bool
    content_hash: str
    uncommitted_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)


class ProjectSnapshot(BaseModel):
    """Immutable snapshot of the target repository state (§7)."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    repository: str
    base_commit: str
    branch: str
    working_tree: WorkingTreeState
    submodules: list[str] = Field(default_factory=list)
    git_remotes: dict[str, str] = Field(default_factory=dict)
    project_size_bytes: int = 0
    tracked_files: list[str] = Field(default_factory=list)
    ignored_files_count: int = 0
    generated_files: list[str] = Field(default_factory=list)
    toolchain_fingerprint: dict[str, str] = Field(default_factory=dict)
    dependency_lock_hashes: dict[str, str] = Field(default_factory=dict)
    policy_version: str = "1.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def calculate_snapshot_hash(self) -> str:
        """Deterministic SHA-256 digest of the snapshot content (§31)."""
        payload = {
            "snapshot_id": self.snapshot_id,
            "repository": self.repository,
            "base_commit": self.base_commit,
            "branch": self.branch,
            "working_tree_hash": self.working_tree.content_hash,
            "dependency_lock_hashes": dict(sorted(self.dependency_lock_hashes.items())),
            "toolchain_fingerprint": dict(sorted(self.toolchain_fingerprint.items())),
            "policy_version": self.policy_version,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class ModuleInfo(BaseModel):
    """Structural module entry within the architecture map (§9)."""

    model_config = ConfigDict(frozen=True)

    id: str
    path: str
    purpose: str | None = None
    public_symbols: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)


class EntrypointInfo(BaseModel):
    """Executable or public entrypoint detected in the project (§9)."""

    model_config = ConfigDict(frozen=True)

    path: str
    symbol: str | None = None
    kind: str = "CLI"  # CLI, API, WEB, SCRIPT, SERVICE


class ExternalDependencyInfo(BaseModel):
    """External dependency detected from lockfiles/manifests (§9)."""

    model_config = ConfigDict(frozen=True)

    package: str
    version: str | None = None
    usage_paths: list[str] = Field(default_factory=list)


class InternalDependencyInfo(BaseModel):
    """Directed dependency link between internal modules (§9)."""

    model_config = ConfigDict(frozen=True)

    from_module: str
    to_module: str


class ArchitectureMap(BaseModel):
    """Reconstructed architectural topology of the project (§9)."""

    model_config = ConfigDict(frozen=True)

    modules: list[ModuleInfo] = Field(default_factory=list)
    entrypoints: list[EntrypointInfo] = Field(default_factory=list)
    external_dependencies: list[ExternalDependencyInfo] = Field(default_factory=list)
    internal_dependencies: list[InternalDependencyInfo] = Field(default_factory=list)
    languages: dict[str, float] = Field(default_factory=dict)
    frameworks: list[str] = Field(default_factory=list)

    def calculate_architecture_hash(self) -> str:
        """Deterministic SHA-256 digest of the architecture map (§31)."""
        payload = {
            "modules": [m.model_dump() for m in self.modules],
            "entrypoints": [e.model_dump() for e in self.entrypoints],
            "external_dependencies": [d.model_dump() for d in self.external_dependencies],
            "internal_dependencies": [i.model_dump() for i in self.internal_dependencies],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class BaselineCheckResult(BaseModel):
    """Outcome of a single diagnostic command in the project baseline (§10)."""

    model_config = ConfigDict(frozen=True)

    check_type: DiagnosticType
    command: str
    exit_code: int
    duration_ms: int
    status: str  # PASS, FAIL, SKIPPED, ERROR
    stdout_hash: str
    stderr_hash: str
    structured_result: dict[str, Any] = Field(default_factory=dict)
    error_count: int = 0
    warning_count: int = 0


class ProjectBaseline(BaseModel):
    """Aggregated project baseline execution record (§10)."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    checks: list[BaselineCheckResult] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def calculate_baseline_hash(self) -> str:
        """Deterministic SHA-256 digest of the baseline checks (§31)."""
        payload = [
            {
                "check_type": c.check_type,
                "command": c.command,
                "exit_code": c.exit_code,
                "status": c.status,
                "stdout_hash": c.stdout_hash,
                "stderr_hash": c.stderr_hash,
            }
            for c in self.checks
        ]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class ContinuationStep(BaseModel):
    """Prioritized follow-up step driven by dependency ordering (§26)."""

    model_config = ConfigDict(frozen=True)

    step_id: str
    title: str
    objective: str
    prerequisites: list[str] = Field(default_factory=list)
    affected_findings: list[str] = Field(default_factory=list)
    affected_paths: list[str] = Field(default_factory=list)
    risk_hint: str = "MEDIUM"
    validation: str
    depends_on: list[str] = Field(default_factory=list)
    estimated_scope: str | None = None


class SuggestedFirstJob(BaseModel):
    """Recommended first actionable job (§27) - purely advisory, never auto-run."""

    model_config = ConfigDict(frozen=True)

    intent: str = "PLANNED_CODE"
    objective: str
    scope: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    risk_hint: str = "MEDIUM"


class ContinuationFreshness(BaseModel):
    """Validation and invalidation metadata for continuation context (§24)."""

    model_config = ConfigDict(frozen=True)

    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    base_commit: str
    working_tree_hash: str
    dependency_hash: str
    architecture_hash: str
    policy_version: str
    state: ContinuationFreshnessState = ContinuationFreshnessState.VALID
    stale_reason: str | None = None


class FindingReportItem(BaseModel):
    """Human and machine readable synthesis of a finding in the report (§17)."""

    model_config = ConfigDict(frozen=True)

    finding_id: str
    explanation: str
    impact: str
    evidence_refs: list[str] = Field(default_factory=list)


class PathConstraint(BaseModel):
    """Sensitive path that should not be modified yet (§17)."""

    model_config = ConfigDict(frozen=True)

    path: str
    reason: str


class UnresolvedQuestion(BaseModel):
    """Explicitly preserved unknown question (§17)."""

    model_config = ConfigDict(frozen=True)

    question: str
    reason: str


class ContinuationReport(BaseModel):
    """Structured output contract of the continuation analyst (§17)."""

    model_config = ConfigDict(frozen=True)

    summary: str
    current_state: str
    architecture_summary: str
    working_area: list[str] = Field(default_factory=list)
    known_good: list[str] = Field(default_factory=list)
    known_broken: list[str] = Field(default_factory=list)

    findings: list[FindingReportItem] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    unresolved_questions: list[UnresolvedQuestion] = Field(default_factory=list)
    recommended_next_steps: list[ContinuationStep] = Field(default_factory=list)
    do_not_touch_yet: list[PathConstraint] = Field(default_factory=list)
    suggested_first_task: SuggestedFirstJob

    context_digest: str | None = None

    def calculate_report_hash(self) -> str:
        """Deterministic SHA-256 digest of the continuation report (§31)."""
        dump = self.model_dump(exclude={"context_digest"})
        raw = json.dumps(dump, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
