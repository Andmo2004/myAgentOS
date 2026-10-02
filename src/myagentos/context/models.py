"""Domain models for structural context compilation, dependency closure, and prompt caching (§9)."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from myagentos.core.models.data_policy import DataClassification, TrustTag


class SymbolKind(StrEnum):
    """Kinds of code symbols extracted deterministically (§9.1)."""

    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    TYPE_ALIAS = "type_alias"
    VARIABLE = "variable"
    IMPORT = "import"


class SymbolInfo(BaseModel):
    """Extracted code symbol with signatures and location (§9.1)."""

    model_config = ConfigDict(frozen=True)

    name: str
    kind: SymbolKind
    file_path: str
    line_number: int
    end_line: int
    signature: str = ""
    docstring: str | None = None
    is_exported: bool = True
    parent: str | None = None


class FileStructuralSummary(BaseModel):
    """Deterministic structural summary of a source file (§9.1)."""

    model_config = ConfigDict(frozen=True)

    path: str
    line_count: int
    sha256: str
    imports: list[str] = Field(default_factory=list)
    imported_names: dict[str, list[str]] = Field(default_factory=dict)
    symbols: list[SymbolInfo] = Field(default_factory=list)
    classification: DataClassification = DataClassification.INTERNAL
    trust: TrustTag = TrustTag.TRUSTED


class RepositoryMap(BaseModel):
    """Structural map of repository tree, manifests, and tests (§9.1)."""

    model_config = ConfigDict(frozen=True)

    root_path: str
    tree_repr: str
    total_files: int
    key_entrypoints: list[str] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    manifest_files: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)


class ContextKind(StrEnum):
    """Context construction targets defined in §9.2 and §6."""

    PLAN_CONTEXT = "PLAN_CONTEXT"
    WORKER_CONTEXT = "WORKER_CONTEXT"
    KNOWLEDGE_CONTEXT = "KNOWLEDGE_CONTEXT"
    CONTINUATION_CONTEXT = "CONTINUATION_CONTEXT"


class CompiledContext(BaseModel):
    """Structure-aware compiled prompt context with prefix caching support (§9.2, §9.7)."""

    model_config = ConfigDict(frozen=True)

    context_kind: ContextKind
    job_id: str
    base_commit: str
    stable_prefix: str = Field(
        ...,
        description=(
            "Static instructions, repo map, and type signatures optimized for prompt caching (§9.7)"
        ),
    )
    variable_suffix: str = Field(
        ...,
        description="Task-specific instructions, active diffs, errors, or expansions (§9.7)",
    )
    total_estimated_tokens: int = 0
    target_files: list[str] = Field(default_factory=list)
    dependency_files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def render_prompt(self) -> str:
        """Renders the composite prompt, preserving prefix stabilization (§9.7)."""
        if not self.stable_prefix.strip():
            return self.variable_suffix.strip()
        if not self.variable_suffix.strip():
            return self.stable_prefix.strip()
        return f"{self.stable_prefix.strip()}\n\n{self.variable_suffix.strip()}"


class ContextExpansionRequest(BaseModel):
    """Request by worker for visible dependency expansion (§9.3)."""

    model_config = ConfigDict(frozen=True)

    reason: str
    symbols: list[str] = Field(default_factory=list)
    paths_suggested: list[str] = Field(default_factory=list)


class ContextExpansionResult(BaseModel):
    """Result of evaluating a context expansion request (§9.3)."""

    model_config = ConfigDict(frozen=True)

    approved: bool
    expanded_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    content_by_path: dict[str, str] = Field(default_factory=dict)
    requires_token_renegotiation: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
