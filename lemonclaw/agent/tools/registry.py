"""Tool registry for dynamic tool management."""

import inspect
import json
import time
from typing import Any

from loguru import logger

from lemonclaw.agent.tools.base import Tool
from lemonclaw.governance import GovernanceRuntime
from lemonclaw.governance.redaction import redact_sensitive_text, redact_sensitive_value
from lemonclaw.ledger.runtime import TaskLedger

_TOOL_ERROR_HINT = "\n\n[Analyze the error above and try a different approach.]"


class ToolRegistry:
    """Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self, governance: GovernanceRuntime | None = None, ledger: TaskLedger | None = None):
        self._tools: dict[str, Tool] = {}
        self._governance = governance
        self._ledger = ledger

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    def _append_tool_trace(
        self,
        *,
        task_id: str,
        trace: dict[str, Any],
    ) -> None:
        if not self._ledger or not task_id:
            return
        task = self._ledger.read_task(task_id)
        if not task:
            return
        metadata = dict(task.get("metadata") or {})
        verification = dict(metadata.get("verification") or {})
        tool_trace = [dict(item) for item in list(verification.get("tool_trace") or []) if isinstance(item, dict)]
        tool_trace.append(dict(trace))
        verification["tool_trace"] = tool_trace[-100:]
        metadata["verification"] = verification
        self._ledger.update_task(task_id, metadata=metadata)

    @staticmethod
    def _build_execute_kwargs(
        tool: Tool,
        params: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Pass user params through untouched, but only inject internal context keys that
        the tool explicitly declares.

        This keeps runtime-only objects (for example TaskLedger) available to internal
        tools like message/notify/task_checkpoint without leaking them into generic
        `**kwargs` tools such as MCP wrappers, where they would be forwarded to external
        servers and fail serialization.
        """
        execute_kwargs = dict(params)
        if not context:
            return execute_kwargs
        try:
            signature = inspect.signature(tool.execute)
        except (TypeError, ValueError):
            return execute_kwargs

        for name, parameter in signature.parameters.items():
            if not name.startswith("_") or name not in context:
                continue
            if parameter.kind not in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            execute_kwargs[name] = context[name]
        return execute_kwargs

    async def execute(
        self,
        name: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Execute a tool by name with given parameters."""
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        step = None
        task_id = ""
        capability_id = ""
        decision = None
        governance_warnings: list[str] = []
        capability = None
        try:
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _TOOL_ERROR_HINT
            started_at = time.time()
            started_at_ms = int(started_at * 1000)
            call_context = dict(context or {})
            capability_id = tool.resolve_capability(params, call_context)
            capability_token = call_context.get("_capability_token")
            mode = str(call_context.get("_mode", "chat"))
            task_id = str(call_context.get("_task_id") or "")
            tenant_id = str(call_context.get("_tenant_id") or "")
            actor_identity = str(call_context.get("_actor_identity") or call_context.get("_agent_id") or "agent")
            if self._governance and capability_token is None:
                capability_token = self._governance.issue_token(
                    task_id=task_id,
                    tenant_id=tenant_id,
                    mode=mode,
                    allowed_capabilities=[capability_id],
                )
                call_context["_capability_token"] = capability_token
            if self._ledger and task_id:
                summary = json.dumps(redact_sensitive_value(params), ensure_ascii=False)[:500]
                replayable = tool.is_replayable(capability_id)
                step = self._ledger.start_step(
                    task_id, step_type="tool_call", name=name,
                    input_summary=summary, replayable=replayable,
                )
                call_context["_step_id"] = step.step_id

            def _finish_blocked_call(reason: str, *, warning_prefix: str) -> str:
                blocked_error = redact_sensitive_text(reason, aggressive=True)[:500]
                governance_warnings.append(f"{warning_prefix}:{blocked_error}")
                ended_at_ms = int(time.time() * 1000)
                if step:
                    self._ledger.finish_step(step, status="failed", error=blocked_error)
                self._append_tool_trace(
                    task_id=task_id,
                    trace={
                        "iteration_index": int(call_context.get("_react_iteration") or 0),
                        "tool_name": name,
                        "step_id": str(getattr(step, "step_id", "") or call_context.get("_step_id") or ""),
                        "capability_id": capability_id,
                        "status": "failed",
                        "ok": False,
                        "replayable": tool.is_replayable(capability_id),
                        "started_at_ms": started_at_ms,
                        "ended_at_ms": ended_at_ms,
                        "params_summary": json.dumps(redact_sensitive_value(params), ensure_ascii=False)[:500],
                        "result_summary": blocked_error,
                        "artifact_refs": [],
                        "warnings": governance_warnings,
                    },
                )
                if self._governance and capability is not None:
                    self._governance.record_audit(
                        capability=capability,
                        token=capability_token,
                        task_id=task_id,
                        mode=mode,
                        actor_identity=actor_identity,
                        started_at=started_at,
                        ended_at=time.time(),
                        params=params,
                        result_status="error",
                        warnings=governance_warnings,
                    )
                return f"Error: {blocked_error}" + _TOOL_ERROR_HINT

            if self._governance:
                decision = self._governance.authorize(
                    capability_id=capability_id,
                    tool_name=name,
                    token=capability_token,
                    tenant_id=tenant_id,
                    mode=mode,
                )
                capability = decision.capability
                governance_warnings = list(decision.warnings or [])
                if not decision.allowed and decision.reason:
                    return _finish_blocked_call(
                        f"Governance denied tool '{name}': {decision.reason}",
                        warning_prefix="denied",
                    )
                sandbox_allowed, sandbox_reason = self._governance.validate_tool_call(
                    capability=capability,
                    params=params,
                    tool=tool,
                )
                if not sandbox_allowed and sandbox_reason:
                    return _finish_blocked_call(
                        f"Sandbox blocked tool '{name}': {sandbox_reason}",
                        warning_prefix="blocked",
                    )

            result = await tool.execute(**self._build_execute_kwargs(tool, params, call_context))
            if isinstance(result, str):
                result = redact_sensitive_text(result)
            else:
                result = redact_sensitive_value(result)
            normalized = tool.normalize_result(result)
            artifact_refs: list[str] = []
            raw_artifacts = normalized.get("artifacts")
            if isinstance(raw_artifacts, list):
                for item in raw_artifacts:
                    if isinstance(item, dict):
                        ref = str(item.get("artifact_id") or item.get("id") or item.get("path") or item.get("uri") or "").strip()
                    else:
                        ref = str(item or "").strip()
                    if ref:
                        artifact_refs.append(ref)
            ended_at_ms = int(time.time() * 1000)
            if step:
                step_status = str(normalized.get("step_status") or ("completed" if normalized.get("ok") else "failed"))
                self._ledger.finish_step(
                    step,
                    status=step_status,
                    error=None if normalized.get("ok") else redact_sensitive_text(str(normalized.get("summary", "")))[:500],
                )
            else:
                step_status = str(normalized.get("step_status") or ("completed" if normalized.get("ok") else "failed"))
            self._append_tool_trace(
                task_id=task_id,
                trace={
                    "iteration_index": int(call_context.get("_react_iteration") or 0),
                    "tool_name": name,
                    "step_id": str(getattr(step, "step_id", "") or call_context.get("_step_id") or ""),
                    "capability_id": capability_id,
                    "status": step_status,
                    "ok": bool(normalized.get("ok")),
                    "replayable": tool.is_replayable(capability_id),
                    "started_at_ms": started_at_ms,
                    "ended_at_ms": ended_at_ms,
                    "params_summary": json.dumps(redact_sensitive_value(params), ensure_ascii=False)[:500],
                    "result_summary": redact_sensitive_text(str(normalized.get("summary") or ""))[:500],
                    "artifact_refs": artifact_refs,
                    "warnings": governance_warnings,
                },
            )
            if self._governance:
                if capability is None:
                    capability = self._governance.authorize(
                        capability_id=capability_id,
                        tool_name=name,
                        token=capability_token,
                        tenant_id=tenant_id,
                        mode=mode,
                    ).capability
                self._governance.record_audit(
                    capability=capability,
                    token=capability_token,
                    task_id=task_id,
                    mode=mode,
                    actor_identity=actor_identity,
                    started_at=started_at,
                    ended_at=time.time(),
                    params=params,
                    result_status="ok" if normalized.get("ok") else "error",
                    warnings=governance_warnings,
                )
            if isinstance(result, str) and result.startswith("Error"):
                return result + _TOOL_ERROR_HINT
            if not isinstance(result, str):
                return json.dumps(normalized, ensure_ascii=False)
            return result
        except Exception as e:
            safe_error = redact_sensitive_text(str(e), aggressive=True)
            logger.warning("Tool '{}' raised {}: {}", name, type(e).__name__, safe_error)
            if self._ledger and task_id:
                if step is not None:
                    self._ledger.finish_step(step, status="failed", error=safe_error[:500])
                else:
                    summary = json.dumps(redact_sensitive_value(params), ensure_ascii=False)[:500]
                    replayable = tool.is_replayable(capability_id) if capability_id else True
                    fallback_step = self._ledger.start_step(
                        task_id,
                        step_type="tool_call",
                        name=name,
                        input_summary=summary,
                        replayable=replayable,
                    )
                    self._ledger.finish_step(fallback_step, status="failed", error=str(e)[:500])
                    step = fallback_step
            self._append_tool_trace(
                task_id=task_id,
                trace={
                    "iteration_index": int((context or {}).get("_react_iteration") or 0),
                    "tool_name": name,
                    "step_id": str(getattr(step, "step_id", "") or ""),
                    "capability_id": capability_id,
                    "status": "failed",
                    "ok": False,
                    "replayable": tool.is_replayable(capability_id) if capability_id else True,
                    "started_at_ms": int(started_at * 1000) if "started_at" in locals() else int(time.time() * 1000),
                    "ended_at_ms": int(time.time() * 1000),
                    "params_summary": json.dumps(redact_sensitive_value(params), ensure_ascii=False)[:500],
                    "result_summary": safe_error[:500],
                    "artifact_refs": [],
                    "warnings": governance_warnings,
                },
            )
            if self._governance and capability is not None:
                self._governance.record_audit(
                    capability=capability,
                    token=capability_token,
                    task_id=task_id,
                    mode=mode,
                    actor_identity=actor_identity,
                    started_at=started_at if "started_at" in locals() else time.time(),
                    ended_at=time.time(),
                    params=params,
                    result_status="error",
                    warnings=governance_warnings,
                )
            return f"Error executing {name}: {safe_error}" + _TOOL_ERROR_HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
