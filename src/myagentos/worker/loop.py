"""Bounded Worker loop coordinating model inference and ToolBroker mediation (§10.2, §10.3)."""

import json
import time

from myagentos.core.models.event import EventActor, EventName
from myagentos.core.models.patch import PatchOperation
from myagentos.core.models.token import CapabilityToken
from myagentos.core.store.event_store import EventStore
from myagentos.gateway.base import LLMMessage
from myagentos.gateway.client import ModelGateway
from myagentos.worker.broker import ToolBroker
from myagentos.worker.models import (
    FileEditProposal,
    PatchProposal,
    ToolCall,
    ToolResult,
    ToolStatus,
    WorkerMode,
    WorkerResult,
    WorkerStep,
)
from myagentos.worktree.patch_applier import apply_patch_set

WORKER_SYSTEM_PROMPT = """You are the Worker agent in Agentic OS.
You operate in the control plane. You have no direct shell or network access.

Available tools:
1. read_file(path: str)
2. search_symbols(query: str, path: str = ".")
3. run_command(command: str)
4. write_file(path: str, content: str)
5. propose_patch(description: str, files: list[dict])

In each turn, respond with a JSON object containing either:
- A tool call:
  {
    "thought": "Your reasoning",
    "tool_call": {
      "name": "read_file",
      "arguments": {"path": "src/main.py"}
    }
  }

- Or the final patch proposal:
  {
    "thought": "Task complete, proposing final patch",
    "propose_patch": {
      "description": "Fix bug in main",
      "files": [
        {
          "path": "src/main.py",
          "operation": "MODIFY",
          "content": "new file content"
        }
      ]
    }
  }
"""


def _parse_model_response(
    raw_text: str,
) -> tuple[str | None, ToolCall | None, PatchProposal | None]:
    """Extracts thought, tool call, or patch proposal from model output."""
    clean = raw_text.strip()
    if clean.startswith("```json"):
        clean = clean[len("```json") :].strip()
    if clean.startswith("```"):
        clean = clean[len("```") :].strip()
    if clean.endswith("```"):
        clean = clean[: -len("```")].strip()

    try:
        data = json.loads(clean)
        thought = data.get("thought")

        if "propose_patch" in data:
            patch_data = data["propose_patch"]
            files: list[FileEditProposal] = []
            for item in patch_data.get("files", []):
                op_raw = str(item.get("operation", "modify")).lower()
                try:
                    op = PatchOperation(op_raw)
                except ValueError:
                    op = PatchOperation.MODIFY
                files.append(
                    FileEditProposal(
                        path=item.get("path", ""),
                        operation=op,
                        content=item.get("content", ""),
                        old_path=item.get("old_path"),
                    )
                )
            proposal = PatchProposal(
                description=patch_data.get("description", "Proposed patch"),
                files=files,
            )
            return thought, None, proposal

        if "tool_call" in data:
            tc_data = data["tool_call"]
            tool_call = ToolCall(
                id=f"tc-{int(time.time() * 1000)}",
                name=tc_data.get("name", ""),
                arguments=tc_data.get("arguments", {}),
            )
            return thought, tool_call, None

    except Exception:
        pass

    return None, None, None


class WorkerLoop:
    """Executes the bounded Worker agent loop (§10.3)."""

    def __init__(
        self,
        gateway: ModelGateway,
        broker: ToolBroker,
        job_id: str,
        token: CapabilityToken,
        model_id: str = "mock-worker",
        event_store: EventStore | None = None,
        mode: WorkerMode = WorkerMode.TOOL_LOOP,
        connection_id: str | None = None,
    ) -> None:
        self.gateway = gateway
        self.broker = broker
        self.job_id = job_id
        self.token = token
        self.model_id = model_id
        self.event_store = event_store
        self.mode = mode
        self.connection_id = connection_id

    def run(self, task_prompt: str) -> WorkerResult:
        """Executes the loop bounded by token steps, time, and budget (§10.3)."""
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=WORKER_SYSTEM_PROMPT),
            LLMMessage(role="user", content=task_prompt),
        ]

        steps: list[WorkerStep] = []
        max_steps = self.token.limits.max_steps

        if self.event_store:
            self.event_store.append(
                job_id=self.job_id,
                actor=EventActor.WORKER,
                state="EXECUTE",
                event_name=EventName.WORKER_STARTED,
                payload={"mode": self.mode.value, "max_steps": max_steps},
            )

        step_idx = 1
        while step_idx <= max_steps:
            if self.token.is_expired():
                return WorkerResult(
                    job_id=self.job_id,
                    success=False,
                    steps=steps,
                    total_steps=len(steps),
                    stop_reason="TIMEOUT",
                )

            # Model Call
            if self.event_store:
                self.event_store.append(
                    job_id=self.job_id,
                    actor=EventActor.WORKER,
                    state="EXECUTE",
                    event_name=EventName.MODEL_CALL_STARTED,
                    payload={"step": step_idx, "model_id": self.model_id},
                )

            t0 = time.time()
            llm_resp = self.gateway.generate(
                messages=messages,
                model_id=self.model_id,
                temperature=0.0,
                connection_id=self.connection_id,
            )
            step_duration = int((time.time() - t0) * 1000)

            if self.event_store:
                self.event_store.append(
                    job_id=self.job_id,
                    actor=EventActor.WORKER,
                    state="EXECUTE",
                    event_name=EventName.MODEL_CALL_COMPLETED,
                    payload={
                        "step": step_idx,
                        "input_tokens": llm_resp.input_tokens,
                        "output_tokens": llm_resp.output_tokens,
                    },
                )

            thought, tool_call, proposal = _parse_model_response(llm_resp.content)

            # 1. Propose Patch (Success termination condition)
            if proposal is not None:
                is_valid, validation_err = self.broker.validate_proposal(proposal)
                if not is_valid:
                    if self.event_store:
                        self.event_store.append(
                            job_id=self.job_id,
                            actor=EventActor.POLICY_ENGINE,
                            state="EXECUTE",
                            event_name=EventName.POLICY_VIOLATION,
                            payload={"error": validation_err},
                        )
                    steps.append(
                        WorkerStep(
                            step_index=step_idx,
                            thought=thought,
                            duration_ms=step_duration,
                            tool_result=ToolResult(
                                call_id=f"proposal-{step_idx}",
                                status=ToolStatus.PERMISSION_DENIED,
                                output="",
                                error=validation_err,
                            ),
                        )
                    )
                    return WorkerResult(
                        job_id=self.job_id,
                        success=False,
                        patch_set=None,
                        steps=steps,
                        total_steps=len(steps),
                        stop_reason="POLICY_VIOLATION",
                    )

                patch_set = self.broker.build_patch_set_from_proposal(self.job_id, proposal)

                applied_ok, err = apply_patch_set(
                    self.broker.worktree_path, patch_set, verify_before_hash=False
                )

                steps.append(
                    WorkerStep(
                        step_index=step_idx,
                        thought=thought,
                        duration_ms=step_duration,
                    )
                )

                if self.event_store:
                    self.event_store.append(
                        job_id=self.job_id,
                        actor=EventActor.WORKER,
                        state="EXECUTE",
                        event_name=EventName.PATCH_CREATED,
                        payload={
                            "files_count": patch_set.total_files,
                            "applied_ok": applied_ok,
                        },
                    )

                return WorkerResult(
                    job_id=self.job_id,
                    success=applied_ok,
                    patch_set=patch_set,
                    steps=steps,
                    total_steps=len(steps),
                    stop_reason="PROPOSE_PATCH" if applied_ok else "ERROR",
                )

            # 2. Tool Execution
            if tool_call is not None:
                if self.event_store:
                    self.event_store.append(
                        job_id=self.job_id,
                        actor=EventActor.TOOL_BROKER,
                        state="EXECUTE",
                        event_name=EventName.TOOL_CALL,
                        payload={
                            "tool_name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    )

                result = self.broker.execute_tool(tool_call)

                steps.append(
                    WorkerStep(
                        step_index=step_idx,
                        thought=thought,
                        tool_call=tool_call,
                        tool_result=result,
                        duration_ms=step_duration,
                    )
                )

                feedback = (
                    f"Tool Result ({tool_call.name}) [{result.trust_tag}]:\n"
                    f"Status: {result.status.value}\n"
                    f"{result.output if result.output else result.error}"
                )
                messages.append(LLMMessage(role="assistant", content=llm_resp.content))
                messages.append(LLMMessage(role="user", content=feedback))

                step_idx += 1
                continue

            # Fallback: unrecognized format
            messages.append(LLMMessage(role="assistant", content=llm_resp.content))
            messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "Please respond with valid JSON containing either 'tool_call' "
                        "or 'propose_patch' matching the specification schema."
                    ),
                )
            )
            steps.append(
                WorkerStep(
                    step_index=step_idx,
                    thought=llm_resp.content,
                    duration_ms=step_duration,
                )
            )
            step_idx += 1

        return WorkerResult(
            job_id=self.job_id,
            success=False,
            steps=steps,
            total_steps=len(steps),
            stop_reason="MAX_STEPS",
        )
