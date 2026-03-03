"""Agent operation tools for multi-agent orchestration."""

from typing import Any, TYPE_CHECKING

from lemonclaw.agent.tools.base import Tool

if TYPE_CHECKING:
    from lemonclaw.agent.registry import AgentRegistry


class CreateAgentTool(Tool):
    """Create a new agent (Player) with a specific role."""

    def __init__(self, registry: "AgentRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "create_agent"

    @property
    def description(self) -> str:
        return (
            "Create a new AI agent (Player) with a specific role and skills. "
            "The agent will run as an independent loop within this instance."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Unique identifier for the agent (e.g. 'writer-1', 'researcher-1')",
                },
                "role": {
                    "type": "string",
                    "description": "Role description (e.g. 'content_writer', 'code_reviewer')",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (optional, defaults to instance model)",
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Custom system prompt for this agent (optional)",
                },
            },
            "required": ["agent_id", "role"],
        }

    async def execute(
        self,
        agent_id: str,
        role: str,
        model: str = "",
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            info = self._registry.create_agent(
                agent_id=agent_id,
                role=role,
                model=model,
                system_prompt_override=system_prompt,
            )
            return f"Agent '{info.agent_id}' created (role={info.role}). It is registered but needs to be started by the system."
        except ValueError as e:
            return f"Error: {e}"


class ListAgentsTool(Tool):
    """List all registered agents."""

    def __init__(self, registry: "AgentRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "list_agents"

    @property
    def description(self) -> str:
        return "List all active agents in this instance with their status and stats."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        agents = self._registry.list_agents()
        if not agents:
            return "No agents registered."
        lines = []
        for a in agents:
            lines.append(
                f"- {a.agent_id} [{a.role}] status={a.status.value} "
                f"model={a.model or 'default'} "
                f"tasks={a.tasks_completed}/{a.tasks_completed + a.tasks_failed} "
                f"success_rate={a.success_rate:.0%}"
            )
        return "\n".join(lines)


class SendToAgentTool(Tool):
    """Send a message to a specific agent."""

    def __init__(self, registry: "AgentRegistry", bus: "Any"):
        self._registry = registry
        self._bus = bus

    @property
    def name(self) -> str:
        return "send_to_agent"

    @property
    def description(self) -> str:
        return (
            "Send a task or message to a specific agent. "
            "The message will be routed to that agent's queue."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Target agent ID",
                },
                "message": {
                    "type": "string",
                    "description": "Message or task to send",
                },
            },
            "required": ["agent_id", "message"],
        }

    async def execute(self, agent_id: str, message: str, **kwargs: Any) -> str:
        from lemonclaw.agent.types import AgentStatus
        from lemonclaw.bus.events import InboundMessage

        info = self._registry.get_agent(agent_id)
        if not info:
            return f"Error: agent '{agent_id}' not found"
        if info.status == AgentStatus.RETIRED:
            return f"Error: agent '{agent_id}' is retired"

        msg = InboundMessage(
            channel="internal",
            sender_id="conductor",
            chat_id=agent_id,
            content=message,
            target_agent_id=agent_id,
        )
        await self._bus.publish_inbound(msg)
        return f"Message sent to agent '{agent_id}'."


class GetAgentStatusTool(Tool):
    """Get detailed status of a specific agent."""

    def __init__(self, registry: "AgentRegistry"):
        self._registry = registry

    @property
    def name(self) -> str:
        return "get_agent_status"

    @property
    def description(self) -> str:
        return "Get detailed status and statistics for a specific agent."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID to query",
                },
            },
            "required": ["agent_id"],
        }

    async def execute(self, agent_id: str, **kwargs: Any) -> str:
        info = self._registry.get_agent(agent_id)
        if not info:
            return f"Error: agent '{agent_id}' not found"
        return (
            f"Agent: {info.agent_id}\n"
            f"Role: {info.role}\n"
            f"Status: {info.status.value}\n"
            f"Model: {info.model or 'default'}\n"
            f"Tasks completed: {info.tasks_completed}\n"
            f"Tasks failed: {info.tasks_failed}\n"
            f"Success rate: {info.success_rate:.0%}\n"
            f"Skills: {', '.join(info.skills) or 'none'}"
        )
