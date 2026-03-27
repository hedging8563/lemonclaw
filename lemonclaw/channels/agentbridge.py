"""AgentBridge channel for coding-agent runtime delivery."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.base import BaseChannel
from lemonclaw.channels.delivery_context import resolve_delivery_session_key
from lemonclaw.gateway.webui.message_schema import serialize_ui_message
from lemonclaw.session.manager import SessionManager


class AgentBridgeChannel(BaseChannel):
    """Bridge-only channel that fans out outbound messages to SSE subscribers."""

    name = "agentbridge"

    def __init__(self, config: Any, bus: Any, *, session_manager: SessionManager):
        super().__init__(config, bus)
        self.session_manager = session_manager
        self._stop_event = asyncio.Event()
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._buffers: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max(1, int(getattr(self.config, "event_buffer_size", 100) or 100)))
        )

    async def start(self) -> None:
        self._running = True
        self._stop_event.clear()
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        for queues in self._subscribers.values():
            for queue in list(queues):
                try:
                    queue.put_nowait({"type": "closed"})
                except asyncio.QueueFull:
                    pass

    def subscribe(self, session_key: str) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[session_key].add(queue)
        backlog = [deepcopy(item) for item in self._buffers.get(session_key, ())]
        return queue, backlog

    def unsubscribe(self, session_key: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        listeners = self._subscribers.get(session_key)
        if not listeners:
            return
        listeners.discard(queue)
        if not listeners:
            self._subscribers.pop(session_key, None)

    def is_session_supported(self, session_key: str) -> bool:
        return session_key.startswith("agentbridge:")

    async def send(self, msg: OutboundMessage) -> None:
        session_key = resolve_delivery_session_key(
            metadata=msg.metadata,
            channel=msg.channel,
            chat_id=msg.chat_id,
        ) or f"{msg.channel}:{msg.chat_id}"
        await self.emit(msg, session_key=session_key)

    async def emit(self, msg: OutboundMessage, *, session_key: str) -> dict[str, Any]:
        event = self._build_event(msg, session_key=session_key)
        self._buffers[session_key].append(deepcopy(event))
        for queue in list(self._subscribers.get(session_key, ())):
            try:
                queue.put_nowait(deepcopy(event))
            except asyncio.QueueFull:
                self._subscribers[session_key].discard(queue)
        if event["type"] == "outbound":
            self._persist_outbound_message(msg, session_key=session_key)
        return event

    def _build_event(self, msg: OutboundMessage, *, session_key: str) -> dict[str, Any]:
        meta = dict(msg.metadata or {})
        if meta.get("_thinking"):
            event_type = "thinking"
            data: Any = str(msg.content)
        elif meta.get("_tool_start"):
            event_type = "tool_start"
            data = str(msg.content)
        elif meta.get("_tool_result"):
            event_type = "tool_result"
            data = str(msg.content)
        elif meta.get("_tool_hint"):
            event_type = "tool_hint"
            data = str(msg.content)
        elif meta.get("_chunk") or meta.get("_progress"):
            event_type = "content"
            data = str(msg.content)
        else:
            event_type = "outbound"
            data = serialize_ui_message(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "media": list(msg.media or []),
                    "timestamp": datetime.now().isoformat(),
                },
                session_key=session_key,
            )
        return {
            "type": event_type,
            "session_key": session_key,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }

    def _persist_outbound_message(self, msg: OutboundMessage, *, session_key: str) -> None:
        session = self.session_manager.get_or_create(session_key)
        session.messages.append(
            serialize_ui_message(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "media": list(msg.media or []),
                    "timestamp": datetime.now().isoformat(),
                },
                session_key=session_key,
            )
        )
        self.session_manager.save(session)

    @staticmethod
    def build_attachment_metadata(path: Path) -> dict[str, Any]:
        return {
            "filename": path.name,
            "size": path.stat().st_size,
        }
