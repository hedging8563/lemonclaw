"""Async message queue for decoupled channel-agent communication."""

import asyncio
import time

from loguru import logger

from lemonclaw.bus.events import InboundMessage, OutboundMessage

DEFAULT_AGENT_ID = "default"


class MessageBus:
    """
    Multi-agent message bus with per-agent inbound routing.

    Channels push messages to the bus, which routes them to the target agent's
    queue based on ``target_agent_id``.  Outbound remains a single shared queue
    consumed by the channel dispatcher.

    Supports request-response via ``request_id``: callers register a Future
    with ``expect_response(request_id)`` and the agent resolves it with
    ``resolve_response(request_id, content)``.

    Backward-compatible: when no agents are registered, behaves like the
    original dual-queue bus (everything goes to the "default" agent).
    """

    def __init__(self, maxsize: int = 200):
        self._maxsize = maxsize
        self._agent_queues: dict[str, asyncio.Queue[InboundMessage]] = {}
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)
        self._pending_responses: dict[str, asyncio.Future[str]] = {}
        self._pending_created_at: dict[str, float] = {}  # request_id -> monotonic time
        # Always register the default agent
        self.register_agent(DEFAULT_AGENT_ID)

    # ── Agent registration ────────────────────────────────────────────────

    def register_agent(self, agent_id: str) -> None:
        """Register an agent and create its inbound queue."""
        if agent_id not in self._agent_queues:
            self._agent_queues[agent_id] = asyncio.Queue(maxsize=self._maxsize)
            logger.debug("Bus: registered agent '{}'", agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent's queue. Messages in flight are discarded."""
        if agent_id != DEFAULT_AGENT_ID:
            self._agent_queues.pop(agent_id, None)
            logger.debug("Bus: unregistered agent '{}'", agent_id)

    @property
    def registered_agents(self) -> list[str]:
        return list(self._agent_queues.keys())

    # ── Inbound (channel → agent) ────────────────────────────────────────

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Route an inbound message to the target agent's queue."""
        target = msg.target_agent_id or DEFAULT_AGENT_ID
        queue = self._agent_queues.get(target)
        if queue is None:
            logger.warning("Bus: no queue for agent '{}', routing to default", target)
            queue = self._agent_queues[DEFAULT_AGENT_ID]
        await queue.put(msg)

    async def consume_inbound(self, agent_id: str = DEFAULT_AGENT_ID) -> InboundMessage:
        """Consume the next inbound message for a specific agent."""
        queue = self._agent_queues.get(agent_id)
        if queue is None:
            raise ValueError(f"Agent '{agent_id}' is not registered")
        return await queue.get()

    # ── Outbound (agent → channels) ──────────────────────────────────────

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from any agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    # ── Request-response (Conductor ↔ Agent) ──────────────────────────────

    def expect_response(self, request_id: str, ttl: float = 600) -> asyncio.Future[str]:
        """Register a Future that will be resolved when an agent responds.

        Args:
            request_id: Unique identifier for this request.
            ttl: Time-to-live in seconds. Stale entries are cleaned up
                 periodically via ``cleanup_stale_responses()``.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_responses[request_id] = fut
        self._pending_created_at[request_id] = time.monotonic()
        return fut

    def resolve_response(self, request_id: str, content: str) -> bool:
        """Resolve a pending request-response Future. Returns True if matched."""
        fut = self._pending_responses.pop(request_id, None)
        self._pending_created_at.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(content)
            return True
        return False

    def cancel_response(self, request_id: str) -> None:
        """Cancel a pending request-response Future."""
        fut = self._pending_responses.pop(request_id, None)
        self._pending_created_at.pop(request_id, None)
        if fut and not fut.done():
            fut.cancel()

    def cleanup_stale_responses(self, max_age: float = 600) -> int:
        """Cancel and remove Futures older than max_age seconds. Returns count cleaned."""
        now = time.monotonic()
        stale = [
            rid for rid, created in self._pending_created_at.items()
            if now - created > max_age
        ]
        for rid in stale:
            self.cancel_response(rid)
        return len(stale)

    # ── Diagnostics ──────────────────────────────────────────────────────

    def inbound_size(self, agent_id: str = DEFAULT_AGENT_ID) -> int:
        queue = self._agent_queues.get(agent_id)
        return queue.qsize() if queue else 0

    @property
    def outbound_size(self) -> int:
        return self.outbound.qsize()
