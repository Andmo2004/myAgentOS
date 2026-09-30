"""Context Compiler package initialization (§9)."""

from myagentos.context.closure import DependencyClosureAnalyzer
from myagentos.context.compiler import ContextCompiler, estimate_tokens
from myagentos.context.extractor import StructuralExtractor
from myagentos.context.models import (
    CompiledContext,
    ContextExpansionRequest,
    ContextExpansionResult,
    ContextKind,
    FileStructuralSummary,
    RepositoryMap,
    SymbolInfo,
    SymbolKind,
)
from myagentos.context.security import (
    PathSecurityError,
    PathSecurityViolation,
    canonicalize_and_verify_path,
    classify_path_and_content,
)

__all__ = [
    "CompiledContext",
    "ContextCompiler",
    "ContextExpansionRequest",
    "ContextExpansionResult",
    "ContextKind",
    "DependencyClosureAnalyzer",
    "FileStructuralSummary",
    "PathSecurityError",
    "PathSecurityViolation",
    "RepositoryMap",
    "StructuralExtractor",
    "SymbolInfo",
    "SymbolKind",
    "canonicalize_and_verify_path",
    "classify_path_and_content",
    "estimate_tokens",
]
