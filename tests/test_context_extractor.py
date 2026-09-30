"""Unit tests for StructuralExtractor AST and signature parsing (§9.1)."""

from pathlib import Path

from myagentos.context.extractor import StructuralExtractor
from myagentos.context.models import SymbolKind


def test_structural_extractor_python_parsing(tmp_path: Path) -> None:
    sample_code = '''"""Sample module docstring."""

from typing import Any
import os

__all__ = ["Calculator", "add"]

class BaseCalc:
    """Base calculator."""
    def reset(self) -> None:
        pass

class Calculator(BaseCalc):
    """Main calculator class."""
    def __init__(self, initial: int = 0) -> None:
        self.val = initial

    def multiply(self, a: int, b: int = 1) -> int:
        """Multiplies two numbers."""
        return a * b

    async def fetch_remote(self, url: str) -> dict[str, Any]:
        return {}

def add(x: int, y: int) -> int:
    """Adds x and y."""
    return x + y

def _private_helper() -> bool:
    return True
'''
    fpath = tmp_path / "calc.py"
    fpath.write_text(sample_code)

    summary = StructuralExtractor.extract_file(fpath, "calc.py")

    assert summary.path == "calc.py"
    assert summary.line_count > 20
    assert "os" in summary.imports
    assert "typing" in summary.imports

    symbols_by_name = {s.name: s for s in summary.symbols}

    # Class BaseCalc
    assert "BaseCalc" in symbols_by_name
    assert symbols_by_name["BaseCalc"].kind == SymbolKind.CLASS
    assert symbols_by_name["BaseCalc"].is_exported is False  # Not in __all__

    # Class Calculator
    assert "Calculator" in symbols_by_name
    assert symbols_by_name["Calculator"].is_exported is True  # In __all__
    assert "BaseCalc" in symbols_by_name["Calculator"].signature

    # Methods
    assert "multiply" in symbols_by_name
    assert symbols_by_name["multiply"].kind == SymbolKind.METHOD
    assert symbols_by_name["multiply"].parent == "Calculator"
    assert "a: int" in symbols_by_name["multiply"].signature

    # Async method
    assert "fetch_remote" in symbols_by_name
    assert "async def fetch_remote" in symbols_by_name["fetch_remote"].signature

    # Functions
    assert "add" in symbols_by_name
    assert symbols_by_name["add"].kind == SymbolKind.FUNCTION
    assert symbols_by_name["add"].is_exported is True

    assert "_private_helper" in symbols_by_name
    assert symbols_by_name["_private_helper"].is_exported is False

    # Format signatures
    formatted = StructuralExtractor.format_signatures(summary)
    assert "class Calculator(BaseCalc):" in formatted
    assert "def multiply(self, a: int, b: int = 1) -> int: ..." in formatted
    assert "def add(x: int, y: int) -> int: ..." in formatted
    assert "return a * b" not in formatted  # Function body omitted!


def test_structural_extractor_syntax_error_fallback(tmp_path: Path) -> None:
    broken_code = """
class IncompleteClass:
    def broken_func(
"""
    fpath = tmp_path / "broken.py"
    fpath.write_text(broken_code)

    # Should not raise SyntaxError, fallback to regex
    summary = StructuralExtractor.extract_file(fpath, "broken.py")
    assert summary.path == "broken.py"
    names = [s.name for s in summary.symbols]
    assert "IncompleteClass" in names
