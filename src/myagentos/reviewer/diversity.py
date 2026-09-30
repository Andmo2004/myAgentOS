"""Model and Provider diversity selection according to §5.3 and §15.1."""

from myagentos.core.models.risk import RiskLevel
from myagentos.gateway.registry import ModelRegistry


class ModelDiversitySelector:
    """Enforces strict model and provider diversity for Independent Review (§5.3)."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()

    def select_reviewer_model(
        self,
        worker_model_id: str,
        risk_level: RiskLevel,
        fallback_model: str = "mock-reviewer",
    ) -> str | None:
        """Selects reviewer model according to Table 5.3 controls.

        - LOW: None (deterministic only)
        - MEDIUM: Distinct model ID (different model)
        - HIGH / CRITICAL: Distinct provider when available
        """
        if risk_level == RiskLevel.LOW:
            return None

        entries = list(self.registry._entries.values())

        # Determine worker provider and model
        worker_entry = next((e for e in entries if e.model_id == worker_model_id), None)
        worker_provider = worker_entry.provider if worker_entry else None

        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            # Prioritize distinct provider (§5.3)
            if worker_provider:
                diff_provider_entries = [
                    e
                    for e in entries
                    if e.provider != worker_provider and e.model_id != worker_model_id
                ]
                if diff_provider_entries:
                    return diff_provider_entries[0].model_id

            # Fallback to distinct model
            diff_model_entries = [e for e in entries if e.model_id != worker_model_id]
            if diff_model_entries:
                return diff_model_entries[0].model_id

            return fallback_model if fallback_model != worker_model_id else "independent-reviewer"

        if risk_level == RiskLevel.MEDIUM:
            # Requires different model (§5.3)
            diff_model_entries = [e for e in entries if e.model_id != worker_model_id]
            if diff_model_entries:
                return diff_model_entries[0].model_id

            return fallback_model if fallback_model != worker_model_id else "independent-reviewer"

        return None
