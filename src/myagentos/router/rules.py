"""Local Router v0: rules, slash commands, and heuristics according to §6."""

import re

from myagentos.core.models.risk import RiskLevel
from myagentos.router.models import RoutingDecision, RoutingIntent


class LocalRouter:
    """Zero-cost local routing engine running completely offline on rules and heuristics (§6)."""

    def __init__(
        self,
        direct_worker_min_confidence: float = 0.92,
        planned_min_confidence: float = 0.80,
        abstain_action: str = "PLAN",
    ) -> None:
        self.direct_worker_min_confidence = direct_worker_min_confidence
        self.planned_min_confidence = planned_min_confidence
        self.abstain_action = abstain_action

    def route(self, prompt: str) -> RoutingDecision:
        trimmed = prompt.strip()

        # 1. Slash commands matching (§6)
        if trimmed.startswith("/direct"):
            cleaned = trimmed[len("/direct") :].strip()
            risk = self._detect_preliminary_risk(cleaned)
            # False-direct prevention: if risk is MEDIUM+, escalate to PLANNED_CODE (§5.4)
            if risk >= RiskLevel.MEDIUM:
                return RoutingDecision(
                    intent=RoutingIntent.PLANNED_CODE,
                    preliminary_risk=risk,
                    confidence=0.95,
                    matched_rule="slash_command_escalated_risk",
                    cleaned_prompt=cleaned,
                )
            return RoutingDecision(
                intent=RoutingIntent.DIRECT_WORKER_CODE,
                preliminary_risk=RiskLevel.LOW,
                confidence=1.0,
                matched_rule="slash_command_direct",
                cleaned_prompt=cleaned,
            )

        if trimmed.startswith("/plan"):
            cleaned = trimmed[len("/plan") :].strip()
            risk = self._detect_preliminary_risk(cleaned)
            return RoutingDecision(
                intent=RoutingIntent.PLANNED_CODE,
                preliminary_risk=max(risk, RiskLevel.MEDIUM),
                confidence=1.0,
                matched_rule="slash_command_plan",
                cleaned_prompt=cleaned,
            )

        if trimmed.startswith("/research"):
            cleaned = trimmed[len("/research") :].strip()
            return RoutingDecision(
                intent=RoutingIntent.DEEP_RESEARCH,
                preliminary_risk=RiskLevel.LOW,
                confidence=1.0,
                matched_rule="slash_command_research",
                cleaned_prompt=cleaned,
            )

        if trimmed.startswith("/doc"):
            cleaned = trimmed[len("/doc") :].strip()
            return RoutingDecision(
                intent=RoutingIntent.DOC_LOOKUP,
                preliminary_risk=RiskLevel.LOW,
                confidence=1.0,
                matched_rule="slash_command_doc",
                cleaned_prompt=cleaned,
            )

        # 2. Heuristics based on text keywords and query structure
        risk = self._detect_preliminary_risk(trimmed)

        # Research intent heuristics
        research_keywords = ["investigate", "benchmark", "state of the art", "compare libraries"]
        if any(kw in trimmed.lower() for kw in research_keywords):
            return RoutingDecision(
                intent=RoutingIntent.DEEP_RESEARCH,
                preliminary_risk=risk,
                confidence=0.85,
                matched_rule="heuristic_research_keywords",
                cleaned_prompt=trimmed,
            )

        # Doc lookup heuristics
        doc_keywords = ["explain architecture", "how does it work", "where is", "read adr"]
        if any(kw in trimmed.lower() for kw in doc_keywords):
            return RoutingDecision(
                intent=RoutingIntent.DOC_LOOKUP,
                preliminary_risk=risk,
                confidence=0.85,
                matched_rule="heuristic_doc_lookup",
                cleaned_prompt=trimmed,
            )

        # High / Critical risk prompts must always be PLANNED_CODE (§5.1 & §6)
        if risk >= RiskLevel.HIGH:
            return RoutingDecision(
                intent=RoutingIntent.PLANNED_CODE,
                preliminary_risk=risk,
                confidence=0.90,
                matched_rule="heuristic_high_risk_plan",
                cleaned_prompt=trimmed,
            )

        # Simple, short, mechanical tasks can qualify for DIRECT_WORKER_CODE
        direct_pattern = r"^(fix typo|rename variable|update docstring|format file|delete unused)\b"
        if re.search(direct_pattern, trimmed, re.IGNORECASE) and len(trimmed) < 120:
            return RoutingDecision(
                intent=RoutingIntent.DIRECT_WORKER_CODE,
                preliminary_risk=RiskLevel.LOW,
                confidence=0.95,
                matched_rule="heuristic_mechanical_direct",
                cleaned_prompt=trimmed,
            )

        # Default fallback to PLANNED_CODE with medium floor (§6)
        return RoutingDecision(
            intent=RoutingIntent.PLANNED_CODE,
            preliminary_risk=max(risk, RiskLevel.MEDIUM),
            confidence=0.82,
            matched_rule="default_planned_fallback",
            cleaned_prompt=trimmed,
        )

    def _detect_preliminary_risk(self, text: str) -> RiskLevel:
        """Inspects text for sensitive keywords to assign preliminary risk."""
        lower = text.lower()

        # Critical triggers
        critical_keywords = [
            ".env",
            "secret",
            "private key",
            "certificate",
            "credentials",
            "ci/cd",
            ".github/workflows",
            "production deploy",
        ]
        if any(kw in lower for kw in critical_keywords):
            return RiskLevel.CRITICAL

        # High triggers
        high_keywords = [
            "auth",
            "login",
            "password",
            "oauth",
            "session",
            "jwt",
            "migration",
            "schema",
            "database",
            "alembic",
            "sql",
            "dockerfile",
            "docker-compose",
            "k8s",
            "kubernetes",
            "pyproject.toml",
            "package.json",
            "lockfile",
            "payment",
            "billing",
            "webhook",
            "signature",
        ]
        if any(kw in lower for kw in high_keywords):
            return RiskLevel.HIGH

        return RiskLevel.LOW
