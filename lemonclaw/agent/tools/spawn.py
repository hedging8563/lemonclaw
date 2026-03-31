"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING

from lemonclaw.agent.tools.base import Tool

if TYPE_CHECKING:
    from lemonclaw.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""
    
    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = ""
        self._origin_chat_id = ""
        self._session_key = ""
    
    def set_context(self, channel: str, chat_id: str, *, session_key: str | None = None) -> None:
        """Set the origin context for subagent announcements.

        When *session_key* is provided it is stored verbatim so that thread
        dimensions (e.g. ``telegram:123:789``) are preserved.  Without it the
        key is reconstructed from *channel* and *chat_id* which loses the
        thread segment.
        """
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = session_key or f"{channel}:{chat_id}"
    
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

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        del params, context
        return "spawn.agent"

    async def execute(
        self,
        task: str,
        label: str | None = None,
        _default_channel: str | None = None,
        _default_chat_id: str | None = None,
        _default_delivery_context: dict[str, Any] | None = None,
        _default_delivery_policy: dict[str, Any] | None = None,
        _session_key: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to execute the given task."""
        if not (_default_channel and _default_chat_id and _session_key):
            return (
                "Error: spawn only works inside an active conversation with delivery context. "
                "Run it from a real chat thread, or provide channel, chat_id, and session_key together."
            )
        origin_channel = _default_channel
        origin_chat_id = _default_chat_id
        session_key = _session_key
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            origin_delivery_context=dict(_default_delivery_context or {}),
            origin_delivery_policy=dict(_default_delivery_policy or {}),
        )
