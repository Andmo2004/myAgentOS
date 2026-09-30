"""Model Registry indexing models by (provider, platform, model_id) according to §7."""

from pydantic import BaseModel, ConfigDict, Field


class ModelEntry(BaseModel):
    """Normalized descriptor of a model deployment (§7)."""

    model_config = ConfigDict(frozen=True)

    provider: str  # e.g., "openai", "google", "mock"
    platform: str  # e.g., "api", "local"
    model_id: str  # exact versioned identifier
    capabilities: list[str] = Field(default_factory=list)  # code_generation, tool_use, etc.
    lifecycle: str = "active"  # active, legacy, deprecated, retired


class ModelRegistry:
    """Registry maintaining active models and resolving by role requirements (§7)."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], ModelEntry] = {}

    def register(self, entry: ModelEntry) -> None:
        key = (entry.provider, entry.platform, entry.model_id)
        self._entries[key] = entry

    def get(self, provider: str, platform: str, model_id: str) -> ModelEntry | None:
        return self._entries.get((provider, platform, model_id))

    def find_by_capabilities(self, required_capabilities: list[str]) -> list[ModelEntry]:
        """Finds all active models fulfilling all required capabilities."""
        results: list[ModelEntry] = []
        for entry in self._entries.values():
            if entry.lifecycle != "active":
                continue
            if all(cap in entry.capabilities for cap in required_capabilities):
                results.append(entry)
        return results
