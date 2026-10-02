"""Unit tests for semantic LLM domain inferencer and abstention."""

from unittest.mock import MagicMock

from myagentos.categorization.inferencer import SemanticInferencer
from myagentos.gateway.base import LLMResponse
from myagentos.gateway.client import ModelGateway


def test_infer_domain_accepted() -> None:
    """Verify inference is accepted when model returns canonical domain with high confidence."""
    mock_gateway = MagicMock(spec=ModelGateway)
    mock_gateway.generate.return_value = LLMResponse(
        content=(
            '{"domain": "Fintech", "confidence": 0.89, '
            '"evidence": ["stripe sdk"], "status": "accepted"}'
        ),
        model_id="mock-categorizer",
    )

    inferencer = SemanticInferencer(gateway=mock_gateway)
    inf = inferencer.infer_domain("payment-service", ["Python"], ["API"], ["payments", "webhooks"])

    assert inf.status == "accepted"
    assert inf.value == "Fintech"
    assert inf.confidence == 0.89
    assert "stripe sdk" in inf.evidence


def test_infer_domain_abstain_low_confidence() -> None:
    """Verify inference abstains when model confidence is below 0.65 threshold (§24)."""
    mock_gateway = MagicMock(spec=ModelGateway)
    mock_gateway.generate.return_value = LLMResponse(
        content=(
            '{"domain": "E-commerce", "confidence": 0.45, "evidence": [], "status": "accepted"}'
        ),
        model_id="mock-categorizer",
    )

    inferencer = SemanticInferencer(gateway=mock_gateway)
    inf = inferencer.infer_domain("ambiguous-repo", ["Python"], [], ["src"])

    assert inf.status == "abstain"
    assert inf.abstain_reason == "insufficient_evidence"


def test_infer_domain_abstain_non_canonical() -> None:
    """Verify inference abstains when model suggests domain outside controlled taxonomy."""
    mock_gateway = MagicMock(spec=ModelGateway)
    mock_gateway.generate.return_value = LLMResponse(
        content=(
            '{"domain": "Astrophysics", "confidence": 0.95, '
            '"evidence": ["telescope"], "status": "accepted"}'
        ),
        model_id="mock-categorizer",
    )

    inferencer = SemanticInferencer(gateway=mock_gateway)
    inf = inferencer.infer_domain("astro-sim", ["Python"], [], ["src"])

    assert inf.status == "abstain"
    assert inf.abstain_reason == "domain_not_in_canonical_taxonomy"


def test_infer_domain_fallback_heuristics() -> None:
    """Verify deterministic fallback when gateway call returns empty or fails."""
    mock_gateway = MagicMock(spec=ModelGateway)
    mock_gateway.generate.side_effect = RuntimeError("Offline")

    inferencer = SemanticInferencer(gateway=mock_gateway)

    # Developer Tools heuristic
    inf_dev = inferencer.infer_domain(
        "myagentos", ["Python"], ["CLI"], ["agent", "cli", "compiler"]
    )
    assert inf_dev.status == "accepted"
    assert inf_dev.value == "Developer Tools"

    # E-commerce heuristic
    inf_ecom = inferencer.infer_domain("shop", ["TypeScript"], ["Web"], ["cart", "checkout"])
    assert inf_ecom.status == "accepted"
    assert inf_ecom.value == "E-commerce"

    # Ambiguous heuristic -> abstention
    inf_amb = inferencer.infer_domain("random", [], [], ["utils"])
    assert inf_amb.status == "abstain"
    assert inf_amb.abstain_reason == "insufficient_evidence"
