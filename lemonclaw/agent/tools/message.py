"""Message tool for sending messages to users."""

from typing import Any, Awaitable, Callable

from lemonclaw.agent.tools.base import Tool
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.delivery_context import DELIVERY_CONTEXT_KEY


class MessageTool(Tool):
    """Tool to send messages to users on chat channels."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._default_message_id = default_message_id
        self._default_delivery_context: dict[str, Any] | None = None
        self._sent_in_turn: bool = False
        self._turn_messages: list[OutboundMessage] = []

    def set_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        delivery_context: dict[str, Any] | None = None,
    ) -> None:
        """Set the current message context."""
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id
        self._default_delivery_context = dict(delivery_context or {}) or None

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    def start_turn(self) -> None:
        """Reset per-turn send tracking."""
        self._sent_in_turn = False
        self._turn_messages = []

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send a message to the user. Use this when you want to communicate something."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, etc.)"
                },
                "chat_id": {
                    "type": "string",
                    "description": "Optional: target chat/user ID"
                },
                "media": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, audio, documents)"
                }
            },
            "required": ["content"]
        }

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        _default_channel: str | None = None,
        _default_chat_id: str | None = None,
        _default_message_id: str | None = None,
        _default_delivery_context: dict[str, Any] | None = None,
        _outbound_sink: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        **kwargs: Any
    ) -> str:
        effective_default_channel = _default_channel or self._default_channel
        effective_default_chat_id = _default_chat_id or self._default_chat_id
        effective_default_message_id = _default_message_id or self._default_message_id
        effective_default_delivery_context = _default_delivery_context or self._default_delivery_context

        channel = channel or effective_default_channel
        chat_id = chat_id or effective_default_chat_id
        message_id = message_id or effective_default_message_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        callback = _outbound_sink or self._send_callback
        if not callback:
            return "Error: Message sending not configured"

        metadata: dict[str, Any] = {}
        same_target = channel == effective_default_channel and chat_id == effective_default_chat_id
        if same_target and effective_default_delivery_context:
            metadata[DELIVERY_CONTEXT_KEY] = dict(effective_default_delivery_context)
        if message_id:
            metadata["message_id"] = message_id

        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata=metadata,
        )

        try:
            await callback(msg)
            if same_target:
                self._sent_in_turn = True
                self._turn_messages.append(msg)
            media_info = f" with {len(media)} attachments" if media else ""
            return f"Message sent to {channel}:{chat_id}{media_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
