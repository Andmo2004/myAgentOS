"""Tool Broker: mediated tool execution bounded strictly by CapabilityTokens (§10.1, §10.3, §23)."""

import hashlib
import re
from fnmatch import fnmatch
from pathlib import Path, PurePath
from typing import Any

from myagentos.core.models.patch import FilePatch, PatchOperation, PatchSet
from myagentos.core.models.token import CapabilityToken
from myagentos.policy.signals import DEFAULT_PROTECTED_PATHS
from myagentos.sandbox.base import SandboxDriver
from myagentos.worker.models import (
    PatchProposal,
    ToolCall,
    ToolResult,
    ToolStatus,
)


def _compute_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ToolBroker:
    """Mediates between the Worker model and the host/sandbox environment (§10.1).

    Enforces that every action satisfies the active CapabilityToken.
    """

    def __init__(
        self,
        worktree_path: str | Path,
        token: CapabilityToken,
        sandbox: SandboxDriver | None = None,
        protected_paths: list[str] | None = None,
    ) -> None:
        self.worktree_path = Path(worktree_path).resolve()
        self.token = token
        self.sandbox = sandbox
        self.protected_paths = protected_paths or DEFAULT_PROTECTED_PATHS

    def _is_path_allowed(self, path: str, allowed_patterns: list[str]) -> bool:
        """Verifies path matches at least one allowed glob pattern and avoids traversal."""
        pure = PurePath(path)
        if pure.is_absolute() or ".." in pure.parts:
            return False
        normalized = path.strip("/")
        return any(
            fnmatch(normalized, pat) or fnmatch(path, pat) or fnmatch(normalized, pat.strip("/"))
            for pat in allowed_patterns
        )

    def _is_protected(self, path: str) -> bool:
        """Verifies if path matches any protected path pattern (§13.2)."""
        normalized = path.strip("/")
        return any(
            fnmatch(normalized, pat) or fnmatch(path, pat) or fnmatch(normalized, pat.strip("/"))
            for pat in self.protected_paths
        )

    def execute_tool(self, call: ToolCall) -> ToolResult:
        """Dispatches a ToolCall against capability bounds and executes it (§10.3)."""
        name = call.name
        args = call.arguments

        try:
            if name == "read_file":
                return self.tool_read_file(call.id, str(args.get("path", "")))
            if name == "search_symbols":
                return self.tool_search_symbols(
                    call.id,
                    str(args.get("query", "")),
                    str(args.get("path", ".")),
                )
            if name == "run_command":
                return self.tool_run_command(call.id, str(args.get("command", "")))
            if name == "write_file":
                return self.tool_write_file(
                    call.id,
                    str(args.get("path", "")),
                    str(args.get("content", "")),
                )
            if name == "propose_patch":
                return self.tool_propose_patch(call.id, args)

            return ToolResult(
                call_id=call.id,
                status=ToolStatus.ERROR,
                output="",
                error=f"Unknown tool: '{name}'",
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                status=ToolStatus.ERROR,
                output="",
                error=f"Tool execution exception: {exc}",
            )

    def tool_read_file(self, call_id: str, path: str) -> ToolResult:
        """Reads a file within the token's read scope (§10.3)."""
        if not path:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error="Path argument is required",
            )

        if not self._is_path_allowed(path, self.token.read_scope):
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.PERMISSION_DENIED,
                output="",
                error=f"Read permission denied for path '{path}' outside read scope",
            )

        target = self.worktree_path / path
        if not target.is_file():
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error=f"File not found: '{path}'",
            )

        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.SUCCESS,
                output=content,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error=f"Failed to read file '{path}': {e}",
            )

    def tool_search_symbols(self, call_id: str, query: str, path: str = ".") -> ToolResult:
        """Searches for regex/symbols in files within read scope."""
        if not self._is_path_allowed(path, self.token.read_scope) and path != ".":
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.PERMISSION_DENIED,
                output="",
                error=f"Search path '{path}' outside read scope",
            )

        target_dir = self.worktree_path / path
        if not target_dir.exists():
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error=f"Directory '{path}' not found",
            )

        results: list[str] = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error=f"Invalid regex query '{query}': {e}",
            )

        # Scan files in read scope
        for fpath in target_dir.rglob("*"):
            if not fpath.is_file():
                continue
            rel = fpath.relative_to(self.worktree_path).as_posix()
            if not self._is_path_allowed(rel, self.token.read_scope):
                continue
            try:
                for idx, line in enumerate(
                    fpath.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                ):
                    if pattern.search(line):
                        results.append(f"{rel}:{idx}: {line.strip()}")
                        if len(results) >= 50:
                            break
            except Exception:
                continue

        output_str = "\n".join(results) if results else "No matches found."
        return ToolResult(call_id=call_id, status=ToolStatus.SUCCESS, output=output_str)

    def tool_run_command(self, call_id: str, command: str) -> ToolResult:
        """Executes authorized command in the Code Sandbox (§10.1, §11)."""
        if not command:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error="Command argument is required",
            )

        # Check against token execute scope
        cmd_parts = command.strip().split()
        binary = cmd_parts[0] if cmd_parts else ""

        is_allowed = any(
            binary == allowed or command.startswith(allowed) for allowed in self.token.execute_scope
        )
        if not is_allowed:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.PERMISSION_DENIED,
                output="",
                error=(
                    f"Execution permission denied for '{command}'. "
                    f"Allowed binaries/prefixes: {self.token.execute_scope}"
                ),
            )

        # Execute inside sandbox driver
        if self.sandbox:
            run_res = self.sandbox.run_command(
                command=command,
                worktree_path=self.worktree_path,
            )
            out = (
                f"Exit code: {run_res.exit_code}\n"
                f"Stdout: {run_res.stdout}\n"
                f"Stderr: {run_res.stderr}"
            )
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.SUCCESS if run_res.exit_code == 0 else ToolStatus.ERROR,
                output=out,
                error=run_res.stderr if run_res.exit_code != 0 else None,
            )

        return ToolResult(
            call_id=call_id,
            status=ToolStatus.ERROR,
            output="",
            error="No active sandbox configured for run_command",
        )

    def tool_write_file(self, call_id: str, path: str, content: str) -> ToolResult:
        """Writes directly to a file within the token write scope (§10.3)."""
        if not path:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error="Path argument is required",
            )

        if self._is_protected(path):
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.PERMISSION_DENIED,
                output="",
                error=f"Modification of protected path '{path}' is strictly forbidden (§13.2)",
            )

        if not self._is_path_allowed(path, self.token.write_scope):
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.PERMISSION_DENIED,
                output="",
                error=f"Write permission denied for '{path}' outside write scope",
            )

        target = self.worktree_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return ToolResult(
            call_id=call_id,
            status=ToolStatus.SUCCESS,
            output=f"Successfully wrote {len(content)} bytes to {path}",
        )

    def tool_propose_patch(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        """Validates and constructs a sealed PatchSet from proposal (§10.4, §12)."""
        try:
            proposal = PatchProposal.model_validate(args)
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                status=ToolStatus.ERROR,
                output="",
                error=f"Invalid patch proposal schema: {e}",
            )

        # Validate write permissions on all proposed files
        for f in proposal.files:
            if self._is_protected(f.path):
                return ToolResult(
                    call_id=call_id,
                    status=ToolStatus.PERMISSION_DENIED,
                    output="",
                    error=f"Patch proposal modifies protected path '{f.path}' (§13.2)",
                )
            if not self._is_path_allowed(f.path, self.token.write_scope):
                return ToolResult(
                    call_id=call_id,
                    status=ToolStatus.PERMISSION_DENIED,
                    output="",
                    error=f"Patch proposal contains path '{f.path}' outside write scope",
                )

        msg = f"Patch proposal accepted for {len(proposal.files)} files: {proposal.description}"
        return ToolResult(
            call_id=call_id,
            status=ToolStatus.SUCCESS,
            output=msg,
        )

    def build_patch_set_from_proposal(
        self,
        job_id: str,
        proposal: PatchProposal,
    ) -> PatchSet:
        """Constructs an authoritative PatchSet stamped with hashes (§12)."""
        file_patches: list[FilePatch] = []

        for item in proposal.files:
            target = self.worktree_path / item.path
            before_hash = ""
            if target.exists() and item.operation in (PatchOperation.MODIFY, PatchOperation.DELETE):
                before_hash = _compute_sha256(target.read_text(encoding="utf-8", errors="ignore"))

            after_hash = ""
            if item.operation in (PatchOperation.CREATE, PatchOperation.MODIFY):
                after_hash = _compute_sha256(item.content)

            file_patches.append(
                FilePatch(
                    path=item.path,
                    operation=item.operation,
                    patch=item.content,
                    old_path=item.old_path,
                    sha256_before=before_hash,
                    sha256_after=after_hash,
                )
            )

        return PatchSet(
            job_id=job_id,
            base_commit=self.token.base_commit,
            files=file_patches,
        )
