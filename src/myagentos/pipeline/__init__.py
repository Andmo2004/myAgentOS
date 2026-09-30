"""Pipeline package initialization and public exports (§8)."""

from myagentos.pipeline.models import PipelineConfig, PipelineResult
from myagentos.pipeline.orchestrator import PipelineOrchestrator

__all__ = [
    "PipelineConfig",
    "PipelineOrchestrator",
    "PipelineResult",
]
