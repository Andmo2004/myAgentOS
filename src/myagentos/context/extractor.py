"""Deterministic AST and structural symbol extractor (§9.1)."""

import ast
import hashlib
import re
from pathlib import Path

from myagentos.context.models import FileStructuralSummary, SymbolInfo, SymbolKind
from myagentos.context.security import classify_path_and_content
from myagentos.core.models.data_policy import TrustTag


class StructuralExtractor:
    """Extracts classes, functions, signatures, imports, and exports without LLM (§9.1)."""

    @classmethod
    def extract_file(
        cls,
        file_path: Path,
        relative_path: str | None = None,
    ) -> FileStructuralSummary:
        """Parses a source file into a deterministic structural summary."""
        rel_path = relative_path or file_path.name
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        line_count = len(content.splitlines())
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        classification = classify_path_and_content(rel_path, content)

        if file_path.suffix == ".py":
            imports, imported_names, symbols = cls._parse_python(content, rel_path)
        else:
            imports, imported_names, symbols = cls._parse_generic(content, rel_path)

        return FileStructuralSummary(
            path=rel_path,
            line_count=line_count,
            sha256=sha256,
            imports=imports,
            imported_names=imported_names,
            symbols=symbols,
            classification=classification,
            trust=TrustTag.TRUSTED,
        )

    @classmethod
    def _parse_python(
        cls,
        code: str,
        rel_path: str,
    ) -> tuple[list[str], dict[str, list[str]], list[SymbolInfo]]:
        imports: list[str] = []
        imported_names: dict[str, list[str]] = {}
        symbols: list[SymbolInfo] = []
        exported_names: set[str] | None = None

        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Fallback to regex-based extraction if syntax is broken
            return cls._parse_python_regex(code, rel_path)

        # 1. Look for __all__ export definition
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                            names: set[str] = set()
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    names.add(elt.value)
                            exported_names = names

        # 2. Extract imports and top-level symbols
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                imports.append(mod)
                imported_names.setdefault(mod, [])
                for alias in node.names:
                    imported_names[mod].append(alias.name)

            elif isinstance(node, ast.ClassDef):
                cls_symbols = cls._process_class_node(node, rel_path, exported_names)
                symbols.extend(cls_symbols)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_sym = cls._process_func_node(node, rel_path, exported_names, parent=None)
                symbols.append(fn_sym)

        return imports, imported_names, symbols

    @classmethod
    def _process_class_node(
        cls,
        node: ast.ClassDef,
        rel_path: str,
        exported_names: set[str] | None,
    ) -> list[SymbolInfo]:
        symbols: list[SymbolInfo] = []
        bases = [cls._unparse_expr(b) for b in node.bases]
        bases_str = f"({', '.join(bases)})" if bases else ""
        docstring = ast.get_docstring(node)
        if exported_names is not None:
            is_exported = node.name in exported_names
        else:
            is_exported = not node.name.startswith("_")

        class_sig = f"class {node.name}{bases_str}"
        symbols.append(
            SymbolInfo(
                name=node.name,
                kind=SymbolKind.CLASS,
                file_path=rel_path,
                line_number=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                signature=class_sig,
                docstring=docstring.split("\n")[0] if docstring else None,
                is_exported=is_exported,
            )
        )

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m_sym = cls._process_func_node(
                    item, rel_path, exported_names=None, parent=node.name
                )
                symbols.append(m_sym)

        return symbols

    @classmethod
    def _process_func_node(
        cls,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        rel_path: str,
        exported_names: set[str] | None,
        parent: str | None,
    ) -> SymbolInfo:
        docstring = ast.get_docstring(node)
        is_async = isinstance(node, ast.AsyncFunctionDef)
        if parent:
            kind = SymbolKind.METHOD
        elif is_async:
            kind = SymbolKind.ASYNC_FUNCTION
        else:
            kind = SymbolKind.FUNCTION

        # Build clean signature
        args_str = cls._format_args(node.args)
        ret_str = f" -> {cls._unparse_expr(node.returns)}" if node.returns else ""
        prefix = "async def " if is_async else "def "
        full_sig = f"{prefix}{node.name}({args_str}){ret_str}"

        is_exported = (
            (node.name in exported_names)
            if exported_names is not None
            else not node.name.startswith("_")
        )

        return SymbolInfo(
            name=node.name,
            kind=kind,
            file_path=rel_path,
            line_number=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=full_sig,
            docstring=docstring.split("\n")[0] if docstring else None,
            is_exported=is_exported,
            parent=parent,
        )

    @classmethod
    def _format_args(cls, args: ast.arguments) -> str:
        parts: list[str] = []

        # Positional-only args
        posonly_offset = len(args.posonlyargs) - len(args.defaults)
        for idx, arg in enumerate(args.posonlyargs):
            ann = f": {cls._unparse_expr(arg.annotation)}" if arg.annotation else ""
            default_val = ""
            if idx >= posonly_offset and posonly_offset >= 0:
                default_val = f" = {cls._unparse_expr(args.defaults[idx - posonly_offset])}"
            parts.append(f"{arg.arg}{ann}{default_val}")
        if args.posonlyargs:
            parts.append("/")

        # Standard args
        defaults_offset = len(args.args) - len(args.defaults)
        for idx, arg in enumerate(args.args):
            ann = f": {cls._unparse_expr(arg.annotation)}" if arg.annotation else ""
            default_val = ""
            default_idx = idx - defaults_offset
            if default_idx >= 0 and default_idx < len(args.defaults):
                default_val = f" = {cls._unparse_expr(args.defaults[default_idx])}"
            parts.append(f"{arg.arg}{ann}{default_val}")

        # Varargs
        if args.vararg:
            ann = f": {cls._unparse_expr(args.vararg.annotation)}" if args.vararg.annotation else ""
            parts.append(f"*{args.vararg.arg}{ann}")
        elif args.kwonlyargs:
            parts.append("*")

        # Keyword-only args
        for arg, default_expr in zip(args.kwonlyargs, args.kw_defaults):
            ann = f": {cls._unparse_expr(arg.annotation)}" if arg.annotation else ""
            default_val = f" = {cls._unparse_expr(default_expr)}" if default_expr else ""
            parts.append(f"{arg.arg}{ann}{default_val}")

        # Kwarg (**kwargs)
        if args.kwarg:
            ann = f": {cls._unparse_expr(args.kwarg.annotation)}" if args.kwarg.annotation else ""
            parts.append(f"**{args.kwarg.arg}{ann}")

        return ", ".join(parts)

    @classmethod
    def _unparse_expr(cls, expr: ast.AST | None) -> str:
        if expr is None:
            return ""
        try:
            return ast.unparse(expr)
        except Exception:
            return ""

    @classmethod
    def _parse_python_regex(
        cls,
        code: str,
        rel_path: str,
    ) -> tuple[list[str], dict[str, list[str]], list[SymbolInfo]]:
        """Fallback regex parser for broken or incomplete Python files."""
        imports: list[str] = []
        symbols: list[SymbolInfo] = []
        lines = code.splitlines()

        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                parts = stripped.split()
                if len(parts) >= 2:
                    imports.append(parts[1])

            elif stripped.startswith("class "):
                m = re.match(r"class\s+([a-zA-Z0-9_]+)", stripped)
                if m:
                    symbols.append(
                        SymbolInfo(
                            name=m.group(1),
                            kind=SymbolKind.CLASS,
                            file_path=rel_path,
                            line_number=idx,
                            end_line=idx,
                            signature=stripped.rstrip(":"),
                        )
                    )
            elif stripped.startswith("def ") or stripped.startswith("async def "):
                m = re.match(r"(async\s+def|def)\s+([a-zA-Z0-9_]+)", stripped)
                if m:
                    symbols.append(
                        SymbolInfo(
                            name=m.group(2),
                            kind=SymbolKind.FUNCTION,
                            file_path=rel_path,
                            line_number=idx,
                            end_line=idx,
                            signature=stripped.rstrip(":"),
                        )
                    )

        return imports, {}, symbols

    @classmethod
    def _parse_generic(
        cls,
        code: str,
        rel_path: str,
    ) -> tuple[list[str], dict[str, list[str]], list[SymbolInfo]]:
        """Extracts structural headings or keys for markdown, json, toml, etc."""
        symbols: list[SymbolInfo] = []
        lines = code.splitlines()

        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                # Markdown heading
                symbols.append(
                    SymbolInfo(
                        name=stripped,
                        kind=SymbolKind.VARIABLE,
                        file_path=rel_path,
                        line_number=idx,
                        end_line=idx,
                        signature=stripped,
                    )
                )

        return [], {}, symbols

    @classmethod
    def format_signatures(cls, summary: FileStructuralSummary) -> str:
        """Formats the file's structural signatures without function/method bodies (§9.1, §9.2)."""
        lines: list[str] = [f"# File: {summary.path} ({summary.line_count} lines)"]

        if summary.imports:
            lines.append(f"# Imports: {', '.join(sorted(set(summary.imports))[:10])}")

        classes = [s for s in summary.symbols if s.kind == SymbolKind.CLASS]
        methods_by_parent: dict[str, list[SymbolInfo]] = {}
        for s in summary.symbols:
            if s.kind == SymbolKind.METHOD and s.parent:
                methods_by_parent.setdefault(s.parent, []).append(s)

        functions = [
            s for s in summary.symbols if s.kind in (SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION)
        ]

        for c in classes:
            doc_snippet = f"  \"\"\"{c.docstring}\"\"\"" if c.docstring else ""
            lines.append(f"{c.signature}:")
            if doc_snippet:
                lines.append(doc_snippet)
            cls_methods = methods_by_parent.get(c.name, [])
            if not cls_methods and not doc_snippet:
                lines.append("  pass")
            else:
                for m in cls_methods:
                    lines.append(f"  {m.signature}: ...")

        for f in functions:
            lines.append(f"{f.signature}: ...")
            if f.docstring:
                lines.append(f"  \"\"\"{f.docstring}\"\"\"")

        return "\n".join(lines)
