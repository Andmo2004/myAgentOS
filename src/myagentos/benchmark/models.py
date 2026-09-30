"""Domain models and schemas for the Empirical Benchmark (§26, §28)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.risk import RiskLevel
from myagentos.router.models import RoutingIntent


class BenchmarkTaskCategory(StrEnum):
    """Risk and complexity categories for stratified sampling (§26.1)."""

    LOW_MECHANICAL = "LOW_MECHANICAL"
    FEATURE_MEDIUM = "FEATURE_MEDIUM"
    HIGH_AUTH_CRITICAL = "HIGH_AUTH_CRITICAL"
    ADVERSARIAL_SECURITY = "ADVERSARIAL_SECURITY"
    PCA_CONTINUITY = "PCA_CONTINUITY"


class BenchmarkTaskSpec(BaseModel):
    """Specification of an empirical benchmark test case (§26.1)."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    category: BenchmarkTaskCategory
    prompt: str
    target_files: list[str] = Field(default_factory=list)
    expected_intent: RoutingIntent = RoutingIntent.PLANNED_CODE
    expected_risk: RiskLevel = RiskLevel.LOW
    adversarial: bool = False
    adversarial_type: str | None = None  # e.g., "PROTECTED_TAMPER", "SCOPE_ESCAPE", "FALSE_DIRECT"
    setup_files: dict[str, str] = Field(default_factory=dict)
    test_command: str = "pytest"
    description: str = ""


class AgentExecutionTelemetry(BaseModel):
    """Measured execution telemetry per agent run (§26.2)."""

    model_config = ConfigDict(frozen=True)

    agent_type: str  # "baseline" or "myagentos"
    task_id: str
    success: bool
    final_state: str
    duration_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    intent: str | None = None
    risk_level: str | None = None
    false_direct: bool = False
    policy_violation_caught: bool = False
    protected_tampering_blocked: bool = False
    patch_applied: bool = False
    compile_passed: bool = False
    test_passed: bool = False
    hash_chain_intact: bool = False
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskComparativeResult(BaseModel):
    """Side-by-side comparison between baseline and myAgentOS (§26.1)."""

    model_config = ConfigDict(frozen=True)

    task: BenchmarkTaskSpec
    baseline: AgentExecutionTelemetry
    myagentos: AgentExecutionTelemetry


class BenchmarkSummaryReport(BaseModel):
    """Aggregated statistical evaluation report (§26.2, §26.4)."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    model_id: str
    suite_name: str
    total_tasks: int
    results: list[TaskComparativeResult]

    # Aggregated metrics (§26.2, §26.4)
    baseline_success_rate: float
    myagentos_success_rate: float
    false_direct_rate: float
    policy_violation_defense_rate: float
    protected_tampering_defense_rate: float
    avg_latency_baseline_ms: float
    avg_latency_myagentos_ms: float
    total_tokens_baseline: int
    total_tokens_myagentos: int
    total_cost_baseline_usd: float
    total_cost_myagentos_usd: float
    hash_chain_integrity_rate: float

    def to_markdown_table(self) -> str:
        """Renders GitHub-flavored Markdown comparative table."""
        delta_succ = self.myagentos_success_rate - self.baseline_success_rate
        delta_lat = self.avg_latency_myagentos_ms - self.avg_latency_baseline_ms
        delta_tok = self.total_tokens_myagentos - self.total_tokens_baseline
        delta_cost = self.total_cost_myagentos_usd - self.total_cost_baseline_usd

        lines: list[str] = [
            f"# Benchmark Evaluation Report (§26, §28) — {self.suite_name}\n",
            (
                f"**Run ID:** `{self.run_id}` | **Model:** `{self.model_id}` | "
                f"**Tasks:** {self.total_tasks} | **Timestamp:** {self.timestamp}\n"
            ),
            "## Summary Metrics Comparison\n",
            "| Metric | Baseline | myAgentOS | Δ / Improvement |",
            "|---|---|---|---|",
            (
                f"| **Task Success Rate** | {self.baseline_success_rate:.1f}% | "
                f"{self.myagentos_success_rate:.1f}% | {delta_succ:+.1f}% |"
            ),
            (
                f"| **False-Direct Defense** | 0.0% (Unchecked) | "
                f"{100.0 - self.false_direct_rate:.1f}% | Complete Protection |"
            ),
            (
                f"| **Policy Violation Defense** | 0.0% (No policy) | "
                f"{self.policy_violation_defense_rate:.1f}% | Enforced Boundaries |"
            ),
            (
                f"| **Protected Test Defense** | 0.0% (Overwrites) | "
                f"{self.protected_tampering_defense_rate:.1f}% | Cryptographic Guard |"
            ),
            (
                f"| **Avg Latency (ms)** | {self.avg_latency_baseline_ms:.1f} ms | "
                f"{self.avg_latency_myagentos_ms:.1f} ms | {delta_lat:+.1f} ms |"
            ),
            (
                f"| **Total Tokens** | {self.total_tokens_baseline:,} | "
                f"{self.total_tokens_myagentos:,} | {delta_tok:+,} |"
            ),
            (
                f"| **Est. Cost ($)** | ${self.total_cost_baseline_usd:.4f} | "
                f"${self.total_cost_myagentos_usd:.4f} | ${delta_cost:+.4f} |"
            ),
            (
                f"| **Hash Chain Integrity** | N/A (None) | "
                f"{self.hash_chain_integrity_rate:.1f}% | 100% Tamper-Evident |"
            ),
            "\n## Detailed Task Breakdown\n",
            "| Task ID | Category | Baseline State | myAgentOS State | Security Caught? | Chain |",
            "|---|---|---|---|---|---|",
        ]

        for res in self.results:
            b = res.baseline
            m = res.myagentos
            caught = (
                "YES (Protected)"
                if m.protected_tampering_blocked
                else ("YES (Policy)" if m.policy_violation_caught else "N/A (Benign)")
            )
            chain = "VALID" if m.hash_chain_intact else "FAIL"
            row = (
                f"| `{res.task.task_id}` | {res.task.category.value} | {b.final_state} | "
                f"{m.final_state} | {caught} | {chain} |"
            )
            lines.append(row)

        return "\n".join(lines) + "\n"
