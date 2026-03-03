"""ActivityBus: broadcast IM activity events to WebSocket clients."""

from __future__ import annotations

import asyncio
from typing import Any


class ActivityBus:
    """Lightweight pub/sub for broadcasting IM events to WebSocket clients.

    Each subscriber gets an asyncio.Queue. Events are broadcast to all
    subscribers; slow consumers are dropped (QueueFull).
    """

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(q)

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in self._clients:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.discard(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)
