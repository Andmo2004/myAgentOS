"""Policy Engine: central deterministic authority for risk and capability tokens (§3, §5, §23)."""

from datetime import UTC, datetime, timedelta

from myagentos.core.models.data_policy import TrustTag
from myagentos.core.models.patch import PatchSet
from myagentos.core.models.plan import PlanSpec
from myagentos.core.models.risk import RiskAssessment, RiskLevel, RiskPhase
from myagentos.core.models.token import CapabilityToken, NetworkScope, TokenLimits
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS, detect_risk_signals
from myagentos.policy.validator import validate_patch_set


class PolicyEngine:
    """Security and governance component enforcing least-privilege tokens and monotonic risk."""

    def __init__(self, protected_paths: list[str] | None = None) -> None:
        self.protected_paths = protected_paths or DEFAULT_PROTECTED_PATHS

    def assess_risk(
        self,
        paths: list[str],
        current_risk: RiskLevel = RiskLevel.LOW,
        phase: RiskPhase = RiskPhase.FINAL,
        evaluator: str = "POLICY_ENGINE",
    ) -> RiskAssessment:
        """Calculates risk level monotonically (§5.1 & §5.2). Risk can only escalate."""
        signals = detect_risk_signals(paths, protected_paths=self.protected_paths)

        # Baseline: size heuristic (>3 files triggers MEDIUM according to §5.3)
        calculated_level = current_risk
        if len(paths) > 3 and calculated_level < RiskLevel.MEDIUM:
            calculated_level = RiskLevel.MEDIUM

        # Elevate according to triggered signals
        for sig in signals:
            if sig.minimum_risk > calculated_level:
                calculated_level = sig.minimum_risk

        # Enforce monotonic escalation from current_risk
        final_level = current_risk.escalate_to(calculated_level)

        return RiskAssessment(
            level=final_level,
            phase=phase,
            evaluator=evaluator,
            signals=signals,
            assessed_at=datetime.now(UTC),
        )

    def assess_patch_risk(
        self,
        patch_set: PatchSet,
        current_risk: RiskLevel,
    ) -> RiskAssessment:
        """Assesses RISK_DIFF based on the actual PatchSet modifications (§5.1)."""
        paths = list(patch_set.affected_paths)
        return self.assess_risk(
            paths=paths,
            current_risk=current_risk,
            phase=RiskPhase.DIFF,
            evaluator="POLICY_ENGINE",
        )

    def issue_capability_token(
        self,
        job_id: str,
        worker_id: str,
        plan: PlanSpec,
        risk_level: RiskLevel,
        ttl_minutes: int = 30,
        skill_tokens: list[CapabilityToken] | None = None,
    ) -> CapabilityToken:
        """Issues an explicit, minimal capability token for a worker (§23).

        Intersection rule: token = plan_scope ∩ policy ∩ skill_permissions.
        """
        # Base token derived from the approved PlanSpec
        read_scope = plan.permissions_requested.get("read", [])
        write_scope = plan.permissions_requested.get("write", [])
        exec_scope = plan.permissions_requested.get("execute", [])

        # Default limits based on risk level
        limits_map = {
            RiskLevel.LOW: TokenLimits(max_files=3, max_diff_lines=150, max_steps=12),
            RiskLevel.MEDIUM: TokenLimits(max_files=6, max_diff_lines=300, max_steps=16),
            RiskLevel.HIGH: TokenLimits(max_files=10, max_diff_lines=500, max_steps=20),
            RiskLevel.CRITICAL: TokenLimits(max_files=5, max_diff_lines=200, max_steps=10),
        }

        token = CapabilityToken(
            job_id=job_id,
            worker_id=worker_id,
            risk_level=risk_level,
            read_scope=read_scope,
            write_scope=write_scope,
            execute_scope=exec_scope,
            network_scope=NetworkScope.NONE,
            limits=limits_map.get(risk_level, TokenLimits()),
            trust=TrustTag.UNTRUSTED,
            base_commit=plan.base_commit,
            expires_at=datetime.now(UTC) + timedelta(minutes=ttl_minutes),
        )

        # Intersect with skills if active (§20 & §23)
        if skill_tokens:
            for s_tok in skill_tokens:
                token = token.intersect_with(s_tok)

        return token

    def validate_patch(
        self,
        patch_set: PatchSet,
        token: CapabilityToken,
    ) -> tuple[bool, list[str]]:
        """Delegates to validate_patch_set using active protected paths."""
        return validate_patch_set(
            patch_set=patch_set,
            token=token,
            protected_paths=self.protected_paths,
        )
