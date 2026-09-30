"""Unit tests for the Local Router v0."""

from myagentos.core.models.risk import RiskLevel
from myagentos.router import LocalRouter, RoutingIntent


def test_router_slash_commands() -> None:
    router = LocalRouter()

    # /plan command
    decision = router.route("/plan refactor user authentication")
    assert decision.intent == RoutingIntent.PLANNED_CODE
    assert decision.preliminary_risk >= RiskLevel.HIGH
    assert decision.confidence == 1.0
    assert decision.cleaned_prompt == "refactor user authentication"

    # /research command
    decision_res = router.route("/research compare pydantic v2 vs msgspec")
    assert decision_res.intent == RoutingIntent.DEEP_RESEARCH
    assert decision_res.cleaned_prompt == "compare pydantic v2 vs msgspec"

    # /doc command
    decision_doc = router.route("/doc where is the database connection defined?")
    assert decision_doc.intent == RoutingIntent.DOC_LOOKUP

    # /continue command (§3 of PCA spec)
    decision_cont = router.route("/continue inspect project health")
    assert decision_cont.intent == RoutingIntent.PROJECT_CONTINUATION
    assert decision_cont.confidence == 1.0
    assert decision_cont.cleaned_prompt == "inspect project health"

    # /audit-project command
    decision_audit = router.route("/audit-project")
    assert decision_audit.intent == RoutingIntent.PROJECT_CONTINUATION

    # Heuristic matching
    decision_heur = router.route("analiza este proyecto y dime cómo continuar")
    assert decision_heur.intent == RoutingIntent.PROJECT_CONTINUATION


def test_router_direct_slash_and_false_direct_escalation() -> None:
    router = LocalRouter()

    # Safe direct command -> DIRECT_WORKER_CODE
    decision_safe = router.route("/direct fix typo in README.md")
    assert decision_safe.intent == RoutingIntent.DIRECT_WORKER_CODE
    assert decision_safe.preliminary_risk == RiskLevel.LOW

    # Direct command targeting sensitive auth files -> escalated to PLANNED_CODE (§5.4 & §6)
    decision_escalated = router.route("/direct modify JWT token signing key")
    assert decision_escalated.intent == RoutingIntent.PLANNED_CODE
    assert decision_escalated.preliminary_risk >= RiskLevel.HIGH


def test_router_heuristics_and_fallbacks() -> None:
    router = LocalRouter()

    # Mechanical small prompt
    decision_mech = router.route("fix typo in calculate_total variable name")
    assert decision_mech.intent == RoutingIntent.DIRECT_WORKER_CODE

    # Complex / general request falls back to PLANNED_CODE with medium floor
    decision_fallback = router.route("Implement stripe webhook handling and verify signatures")
    assert decision_fallback.intent == RoutingIntent.PLANNED_CODE
    assert decision_fallback.preliminary_risk >= RiskLevel.HIGH
