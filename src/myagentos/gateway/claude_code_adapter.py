"""Claude Code CLI adapter delegating inference without handling credentials (§5.1, §7.1, §8.1).

Follows specifications from
docs/new_features/agentic-os-feature-model-plan-connect-v2.md
(AO-MODEL-PLAN-CONNECT-01, Route B).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from myagentos.gateway.base import LLMMessage, LLMResponse, ProviderAdapter
from myagentos.gateway.credentials import CredentialStatus, IdentityInfo
from myagentos.gateway.discovery import DiscoveredModel
from myagentos.gateway.plan_connection import (
    ConnectionPlatform,
    PlanConnectionError,
    PlanConnectionProfile,
    PlanUsageLimitError,
)

# Environment variables to purge before launching Claude Code (§5.1)
PURGED_ENV_VARS: set[str] = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_REGION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "VERTEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
}


def build_sanitized_environment(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Strips API keys and cloud credentials from the child environment (§5.1)."""
    source = dict(base_env if base_env is not None else os.environ)
    for var in PURGED_ENV_VARS:
        source.pop(var, None)
    return source


class ClaudeCodeAdapter(ProviderAdapter):
    """Adapter delegating inference to local 'claude -p' with tools disabled (§7.1).

    Guarantees:
    - Never stores, logs, or copies Claude credentials or session files.
    - Strips all API keys from child environment to prevent accidental API billing.
    - Enforces concurrency limit of 1.
    - Aborts immediately with SIGKILL if any tool_use event is observed in the stream.
    - Validates that authMethod is strictly 'claude.ai' before accepting the connection.
    """

    DECLARED_MODELS: list[tuple[str, str]] = [
        ("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet (Latest)"),
        ("claude-3-5-haiku-latest", "Claude 3.5 Haiku (Latest)"),
        ("claude-3-opus-latest", "Claude 3 Opus (Latest)"),
    ]

    def __init__(
        self,
        connection_id: str = "conn-anthropic-claude-code",
        connection_profile: PlanConnectionProfile | None = None,
        claude_binary: str = "claude",
        timeout_seconds: float = 120.0,
        process_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.connection_id = (
            connection_profile.connection_id if connection_profile else connection_id
        )
        self.connection_profile: PlanConnectionProfile | None = connection_profile
        self.claude_binary = claude_binary
        self.timeout_seconds = timeout_seconds
        self.process_runner = process_runner
        self._concurrency_lock = threading.Semaphore(1)

    def _resolve_binary(self) -> str | None:
        """Finds executable path for the claude CLI binary."""
        return shutil.which(self.claude_binary)

    def validate_credential(self) -> tuple[CredentialStatus, str | None, IdentityInfo | None]:
        """Validates that Claude Code is installed and active session is claude.ai (§5.1)."""
        bin_path = self._resolve_binary()
        if not bin_path and not self.process_runner:
            return (
                CredentialStatus.PROVIDER_UNAVAILABLE,
                f"Claude Code binary '{self.claude_binary}' not found in PATH",
                None,
            )

        cmd = [bin_path or self.claude_binary, "auth", "status"]
        clean_env = build_sanitized_environment()

        try:
            if self.process_runner:
                output_text = self.process_runner(cmd, env=clean_env)
            else:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=clean_env,
                    timeout=15,
                    check=False,
                )
                output_text = proc.stdout

            data = json.loads(output_text) if output_text.strip() else {}
            auth_method = data.get("authMethod")
            if auth_method != "claude.ai":
                return (
                    CredentialStatus.INVALID,
                    f"Claude Code authMethod is '{auth_method}'; expected 'claude.ai'. "
                    f"Please run 'claude auth login' with your Claude subscription.",
                    None,
                )

            account_label = (
                data.get("email") or data.get("account") or "Claude Pro/Max Account"
            )
            return (
                CredentialStatus.VALID,
                None,
                IdentityInfo(principal_name=account_label, principal_type="account"),
            )
        except Exception as e:
            return (
                CredentialStatus.PROVIDER_UNAVAILABLE,
                f"Failed to check Claude Code auth status: {e}",
                None,
            )

    def discover_models(self) -> list[DiscoveredModel]:
        """Returns declared subscription models for Claude (§6)."""
        return [
            DiscoveredModel(
                model_id=slug,
                provider="anthropic",
                display_name=name,
                raw_capabilities=["code_generation", "tool_use", "structured_output"],
            )
            for slug, name in self.DECLARED_MODELS
        ]

    def generate(
        self,
        messages: list[LLMMessage],
        model_id: str,
        temperature: float = 0.0,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        """Executes 'claude -p' with tools disabled and returns LLMResponse (§7.1)."""
        bin_path = self._resolve_binary()
        if not bin_path and not self.process_runner:
            raise PlanConnectionError(
                f"Claude Code binary '{self.claude_binary}' not found in PATH",
                platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
            )

        # Enforce concurrency 1 (§7.1)
        acquired = self._concurrency_lock.acquire(timeout=self.timeout_seconds)
        if not acquired:
            raise PlanConnectionError(
                "Timed out waiting for Claude Code single-concurrency lock",
                platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="myagentos_claude_"))
        system_prompt_file = temp_dir / "system.txt"
        clean_env = build_sanitized_environment()

        try:
            system_content = "\n\n".join(m.content for m in messages if m.role == "system")
            user_content = "\n\n".join(m.content for m in messages if m.role != "system")

            if response_schema:
                schema_name = getattr(response_schema, "__name__", "StructuredOutput")
                extra_instruction = (
                    f"\n\nIMPORTANT: Output strictly valid JSON conforming to the schema "
                    f"'{schema_name}'. Return ONLY valid JSON, no explanations."
                )
                user_content += extra_instruction

            # Secure file with 0600 mode
            fd = os.open(str(system_prompt_file), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                f.write(system_content or "You are an assistant.")

            # Flags according to Section 7.1 and S8
            cmd = [
                bin_path or self.claude_binary,
                "-p",
                "--output-format",
                "stream-json",
                "--verbose",
                "--tools",
                "",
                "--disallowedTools",
                "mcp__*",
                "--strict-mcp-config",
                "--no-session-persistence",
                "--disable-slash-commands",
                "--system-prompt-file",
                str(system_prompt_file),
                "--max-turns",
                "1",
                "--model",
                model_id,
            ]

            if self.process_runner:
                try:
                    raw_output = self.process_runner(cmd, input_text=user_content, env=clean_env)
                except TypeError:
                    raw_output = self.process_runner(cmd, env=clean_env)

                if isinstance(raw_output, dict):
                    accumulated_text = raw_output.get("text", "")
                    input_tokens = raw_output.get("input_tokens", 15)
                    output_tokens = raw_output.get("output_tokens", 25)
                else:
                    lines = str(raw_output).splitlines()
                    accumulated_text = ""
                    input_tokens = 0
                    output_tokens = 0
                    for line_str in lines:
                        line_str = line_str.strip()
                        if not line_str:
                            continue
                        try:
                            event = json.loads(line_str)
                        except Exception:
                            continue

                        # STRICT SECURITY RULE: Abort immediately on tool_use (§7.1)
                        if event.get("type") == "tool_use" or "tool_use" in str(event):
                            raise PlanConnectionError(
                                "External tool execution is prohibited: unauthorized tool_use "
                                "detected in Claude Code stream",
                                platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
                            )
                        if event.get("type") == "text":
                            accumulated_text += event.get("text", "")
                        elif event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                accumulated_text += delta.get("text", "")
                        elif event.get("type") == "result":
                            accumulated_text = event.get("result", accumulated_text)
                            usage = event.get("usage", {})
                            input_tokens = usage.get("input_tokens", input_tokens)
                            output_tokens = usage.get("output_tokens", output_tokens)
                        elif event.get("type") == "message_delta":
                            usage = event.get("usage", {})
                            input_tokens = usage.get("input_tokens", input_tokens)
                            output_tokens = usage.get("output_tokens", output_tokens)
            else:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(temp_dir),
                    env=clean_env,
                    start_new_session=True,
                )

                accumulated_text = ""
                input_tokens = 0
                output_tokens = 0

                try:
                    # Write user prompt via stdin
                    if proc.stdin:
                        proc.stdin.write(user_content)
                        proc.stdin.close()

                    # Stream JSON line by line
                    start_time = time.monotonic()
                    while True:
                        if (time.monotonic() - start_time) > self.timeout_seconds:
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                            except (ProcessLookupError, PermissionError):
                                proc.kill()
                            raise PlanConnectionError(
                                f"Claude Code execution timed out after {self.timeout_seconds}s",
                                platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
                            )

                        line = proc.stdout.readline() if proc.stdout else ""
                        if not line and proc.poll() is not None:
                            break
                        if not line:
                            continue

                        line_str = line.strip()
                        try:
                            event = json.loads(line_str)
                        except Exception:
                            continue

                        # STRICT SECURITY RULE: Abort immediately on tool_use (§7.1)
                        if event.get("type") == "tool_use" or "tool_use" in str(event):
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                            except (ProcessLookupError, PermissionError):
                                proc.kill()
                            raise PlanConnectionError(
                                "External tool execution is prohibited: unauthorized tool_use "
                                "detected in Claude Code stream",
                                platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
                            )

                        if event.get("type") == "text":
                            accumulated_text += event.get("text", "")
                        elif event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                accumulated_text += delta.get("text", "")
                        elif event.get("type") == "result":
                            accumulated_text = event.get("result", accumulated_text)
                            usage = event.get("usage", {})
                            input_tokens = usage.get("input_tokens", input_tokens)
                            output_tokens = usage.get("output_tokens", output_tokens)
                        elif event.get("type") == "message_delta":
                            usage = event.get("usage", {})
                            input_tokens = usage.get("input_tokens", input_tokens)
                            output_tokens = usage.get("output_tokens", output_tokens)

                    stderr_out = proc.stderr.read() if proc.stderr else ""
                    if proc.returncode != 0:
                        err_lower = stderr_out.lower()
                        if "usage limit" in err_lower or "rate limit" in err_lower:
                            raise PlanUsageLimitError(
                                f"Claude plan usage limit exceeded: {stderr_out}",
                                platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
                                code="quota_exhausted",
                            )
                        raise PlanConnectionError(
                            f"Claude Code exited with status {proc.returncode}: {stderr_out}",
                            platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
                        )

                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        proc.kill()
                    raise

            # Local Pydantic validation if schema requested (§7.1)
            if response_schema:
                clean_json = accumulated_text.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[len("```json") :].strip()
                if clean_json.startswith("```"):
                    clean_json = clean_json[len("```") :].strip()
                if clean_json.endswith("```"):
                    clean_json = clean_json[: -len("```")].strip()
                try:
                    response_schema.model_validate_json(clean_json)
                except Exception as e:
                    raise PlanConnectionError(
                        f"Local structured output validation failed for "
                        f"{response_schema.__name__}: {e}",
                        platform=ConnectionPlatform.CLAUDE_CODE_PLAN.value,
                    ) from e

            return LLMResponse(
                content=accumulated_text,
                tool_calls=[],
                input_tokens=input_tokens or len(" ".join(m.content for m in messages).split()),
                output_tokens=output_tokens or len(accumulated_text.split()),
                model_id=model_id,
            )

        finally:
            self._concurrency_lock.release()
            # Clean up temp directory and prompt file
            shutil.rmtree(str(temp_dir), ignore_errors=True)
