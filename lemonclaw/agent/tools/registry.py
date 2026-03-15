"""Tool registry for dynamic tool management."""

import json
import time
from typing import Any

from loguru import logger

from lemonclaw.agent.tools.base import Tool
from lemonclaw.governance import GovernanceRuntime
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
        try:
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _TOOL_ERROR_HINT
            started_at = time.time()
            call_context = dict(context or {})
            capability_id = tool.resolve_capability(params, call_context)
            capability_token = call_context.get("_capability_token")
            mode = str(call_context.get("_mode", "chat"))
            task_id = str(call_context.get("_task_id") or "")
            tenant_id = str(call_context.get("_tenant_id") or "")
            actor_identity = str(call_context.get("_actor_identity") or call_context.get("_agent_id") or "agent")
            if self._ledger and task_id:
                summary = json.dumps(params, ensure_ascii=False)[:500]
                replayable = tool.is_replayable(capability_id)
                step = self._ledger.start_step(
                    task_id, step_type="tool_call", name=name,
                    input_summary=summary, replayable=replayable,
                )
                call_context["_step_id"] = step.step_id

            if self._governance:
                decision = self._governance.authorize(
                    capability_id=capability_id,
                    tool_name=name,
                    token=capability_token,
                    tenant_id=tenant_id,
                    mode=mode,
                )
                if not decision.allowed:
                    ended_at = time.time()
                    self._governance.record_audit(
                        capability=decision.capability,
                        token=capability_token,
                        task_id=task_id,
                        mode=mode,
                        actor_identity=actor_identity,
                        started_at=started_at,
                        ended_at=ended_at,
                        params=params,
                        result_status="denied",
                    )
                    if step:
                        self._ledger.finish_step(step, status="failed", error=f"denied: {decision.reason}")
                    return f"Error: Capability '{capability_id}' denied: {decision.reason}" + _TOOL_ERROR_HINT

            result = await tool.execute(**params, **call_context)
            normalized = tool.normalize_result(result)
            if step:
                step_status = str(normalized.get("step_status") or ("completed" if normalized.get("ok") else "failed"))
                self._ledger.finish_step(
                    step,
                    status=step_status,
                    error=None if normalized.get("ok") else str(normalized.get("summary", ""))[:500],
                )
            if self._governance:
                decision = self._governance.authorize(
                    capability_id=capability_id,
                    tool_name=name,
                    token=capability_token,
                    tenant_id=tenant_id,
                    mode=mode,
                )
                self._governance.record_audit(
                    capability=decision.capability,
                    token=capability_token,
                    task_id=task_id,
                    mode=mode,
                    actor_identity=actor_identity,
                    started_at=started_at,
                    ended_at=time.time(),
                    params=params,
                    result_status="ok" if normalized.get("ok") else "error",
                )
            if isinstance(result, str) and result.startswith("Error"):
                return result + _TOOL_ERROR_HINT
            if not isinstance(result, str):
                return json.dumps(normalized, ensure_ascii=False)
            return result
        except Exception as e:
            logger.warning("Tool '{}' raised {}: {}", name, type(e).__name__, e)
            if self._ledger and task_id:
                if step is not None:
                    self._ledger.finish_step(step, status="failed", error=str(e)[:500])
                else:
                    summary = json.dumps(params, ensure_ascii=False)[:500]
                    replayable = tool.is_replayable(capability_id) if capability_id else True
                    fallback_step = self._ledger.start_step(
                        task_id,
                        step_type="tool_call",
                        name=name,
                        input_summary=summary,
                        replayable=replayable,
                    )
                    self._ledger.finish_step(fallback_step, status="failed", error=str(e)[:500])
            return f"Error executing {name}: {str(e)}" + _TOOL_ERROR_HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
