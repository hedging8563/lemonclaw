"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING

from lemonclaw.agent.tools.base import Tool

if TYPE_CHECKING:
    from lemonclaw.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""
    
    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"
    
    @property
    def name(self) -> str:
        return "spawn"
    
    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }
    
    async def execute(
        self,
        task: str,
        label: str | None = None,
        _default_channel: str | None = None,
        _default_chat_id: str | None = None,
        _session_key: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to execute the given task."""
        origin_channel = _default_channel or self._origin_channel
        origin_chat_id = _default_chat_id or self._origin_chat_id
        if _session_key:
            session_key = _session_key
        elif _default_channel or _default_chat_id:
            session_key = f"{origin_channel}:{origin_chat_id}"
        else:
            session_key = self._session_key or f"{origin_channel}:{origin_chat_id}"
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
        )
