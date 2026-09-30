"""Semantic LLM inferencer proposing domain categorizations with explicit abstention.

Follows §4.2, §7, §8 (Fase D), §23, and §24 of the feature specification:
docs/agentic-os-feature-project-categorization.md
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from myagentos.categorization.models import Inference
from myagentos.categorization.taxonomy import DOMAINS, normalize_tag_label
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway

logger = logging.getLogger(__name__)

INFERENCE_SYSTEM_PROMPT = """\
You are the semantic domain categorizer for Agentic OS.
Your task is to infer the primary business or application domain of the repository.

Supported Domains:
- E-commerce
- Fintech
- Health
- Education
- Productivity
- Developer Tools
- Analytics
- Media
- Gaming
- Security
- AI/ML

Rules:
1. Base your proposal strictly on concrete evidence (directory names, dependencies, manifests).
2. If evidence is ambiguous, contradictory, or insufficient, you MUST ABSTAIN.
3. You have no tools and cannot execute code.
4. Output ONLY valid JSON matching this schema:
{
  "domain": "Canonical Domain Name or null",
  "confidence": 0.85,
  "evidence": ["evidence item 1", "evidence item 2"],
  "status": "accepted",  // or "abstain"
  "abstain_reason": null // or reason string if abstaining
}
"""


class DomainInferenceSchema(BaseModel):
    """Schema for validating LLM semantic domain output."""

    model_config = ConfigDict(frozen=True)

    domain: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    status: str = "accepted"
    abstain_reason: str | None = None


def _clean_json(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```json"):
        clean = clean[7:].strip()
    elif clean.startswith("```"):
        clean = clean[3:].strip()
    if clean.endswith("```"):
        clean = clean[:-3].strip()
    return clean


class SemanticInferencer:
    """Dispatches bounded inference through ModelGateway to propose domain categorizations."""

    def __init__(self, gateway: ModelGateway, model_id: str = "mock-categorizer") -> None:
        self.gateway = gateway
        self.model_id = model_id

    def infer_domain(
        self,
        repo_name: str,
        detected_stack: list[str],
        detected_apps: list[str],
        key_paths: list[str],
    ) -> Inference:
        """Proposes a domain inference with evidence and confidence, or abstains (§24)."""
        user_prompt = (
            f"Repository name: {repo_name}\n"
            f"Detected stack: {', '.join(detected_stack)}\n"
            f"Detected applications: {', '.join(detected_apps)}\n"
            f"Key directory paths: {', '.join(key_paths[:30])}\n"
        )

        messages = [
            LLMMessage(role="system", content=INFERENCE_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        raw_output = ""
        try:
            resp = self.gateway.generate(
                messages=messages,
                model_id=self.model_id,
                temperature=0.0,
                response_schema=DomainInferenceSchema,
            )
            raw_output = resp.content
        except Exception as exc:
            logger.debug("ModelGateway call failed in SemanticInferencer: %s", exc)

        # Attempt to parse output
        clean = _clean_json(raw_output)
        parsed: DomainInferenceSchema | None = None
        if clean:
            try:
                data = json.loads(clean)
                if isinstance(data, dict):
                    parsed = DomainInferenceSchema.model_validate(data)
            except Exception:
                parsed = None

        # Fallback heuristic / mock handling
        if not parsed or (not parsed.domain and parsed.status == "accepted"):
            parsed = self._fallback_inference(repo_name, detected_stack, key_paths)

        # Enforce validation and abstention (§24)
        if parsed.confidence < 0.65 or not parsed.domain:
            return Inference(
                key="domain",
                value="Unknown",
                confidence=parsed.confidence,
                evidence=parsed.evidence,
                generated_by="semantic_inferencer",
                generated_at=datetime.now(UTC),
                status="abstain",
                abstain_reason=parsed.abstain_reason or "insufficient_evidence",
            )

        canonical_domain = normalize_tag_label(parsed.domain)
        if canonical_domain not in DOMAINS:
            # Domain not in canonical catalog, abstain
            return Inference(
                key="domain",
                value=parsed.domain,
                confidence=parsed.confidence,
                evidence=parsed.evidence,
                generated_by="semantic_inferencer",
                generated_at=datetime.now(UTC),
                status="abstain",
                abstain_reason="domain_not_in_canonical_taxonomy",
            )

        return Inference(
            key="domain",
            value=canonical_domain,
            confidence=parsed.confidence,
            evidence=parsed.evidence,
            generated_by="semantic_inferencer",
            generated_at=datetime.now(UTC),
            status="accepted",
        )

    def _fallback_inference(
        self,
        repo_name: str,
        stack: list[str],
        paths: list[str],
    ) -> DomainInferenceSchema:
        """Deterministic fallback when running with mock adapter or offline."""
        all_text = f"{repo_name} {' '.join(stack)} {' '.join(paths)}".lower()

        # E-commerce signals (§4.4)
        if any(w in all_text for w in ["cart", "checkout", "order", "stripe", "payment"]):
            return DomainInferenceSchema(
                domain="E-commerce",
                confidence=0.88,
                evidence=["Detected cart/checkout paths or payment dependencies"],
                status="accepted",
            )

        # Developer Tools signals
        if any(w in all_text for w in ["agent", "cli", "sdk", "compiler", "linter", "benchmark"]):
            return DomainInferenceSchema(
                domain="Developer Tools",
                confidence=0.92,
                evidence=["Detected compiler/agent/CLI architectural modules"],
                status="accepted",
            )

        # AI/ML signals
        if any(w in all_text for w in ["torch", "tensorflow", "onnx", "model", "inference", "llm"]):
            return DomainInferenceSchema(
                domain="AI/ML",
                confidence=0.85,
                evidence=["Detected machine learning and model inference keywords"],
                status="accepted",
            )

        # Insufficient evidence -> abstain (§24)
        return DomainInferenceSchema(
            domain=None,
            confidence=0.3,
            evidence=[],
            status="abstain",
            abstain_reason="insufficient_evidence",
        )
