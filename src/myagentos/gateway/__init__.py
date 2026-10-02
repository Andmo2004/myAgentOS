"""Model Gateway and provider adapter exports."""

from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.claude_adapter import ClaudeAdapter
from myagentos.gateway.client import ModelGateway
from myagentos.gateway.credentials import (
    CredentialProfile,
    CredentialStatus,
    IdentityInfo,
    derive_fingerprint,
)
from myagentos.gateway.discovery import (
    DiscoveredModel,
    DiscoveredModelSet,
    DiscoveryCache,
    EffectiveModelSet,
)
from myagentos.gateway.gemini_adapter import GeminiAdapter
from myagentos.gateway.mock_adapter import MockProviderAdapter
from myagentos.gateway.openai_adapter import OpenAIAdapter
from myagentos.gateway.registry import ModelEntry, ModelRegistry

__all__ = [
    "ModelGateway",
    "ModelRegistry",
    "ModelEntry",
    "ProviderAdapter",
    "LLMMessage",
    "LLMResponse",
    "MockProviderAdapter",
    "OpenAIAdapter",
    "GeminiAdapter",
    "ClaudeAdapter",
    "CredentialProfile",
    "CredentialStatus",
    "IdentityInfo",
    "derive_fingerprint",
    "DiscoveredModel",
    "DiscoveredModelSet",
    "DiscoveryCache",
    "EffectiveModelSet",
]
