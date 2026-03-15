"""Shared runtime context for gateway route wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.bus.activity import ActivityBus
    from lemonclaw.channels.manager import ChannelManager
    from lemonclaw.ledger.outbox import OutboxDispatcher
    from lemonclaw.session.manager import SessionManager
    from lemonclaw.telemetry.usage import UsageTracker
    from lemonclaw.watchdog.service import WatchdogService


@dataclass(slots=True)
class GatewayRuntimeContext:
    """Registry of runtime objects shared across gateway routes.

    This is intentionally a pragmatic runtime registry, not a strict DI
    container. It reduces long parameter pass-through chains while making
    the available runtime dependencies explicit.
    """

    version: str = "unknown"
    model: str = ""
    instance_id: str = ""
    start_time: float = 0.0
    channel_manager: "ChannelManager | None" = None
    usage_tracker: "UsageTracker | None" = None
    session_manager: "SessionManager | None" = None
    agent_loop: "AgentLoop | None" = None
    watchdog: "WatchdogService | None" = None
    activity_bus: "ActivityBus | None" = None
    outbox_dispatcher: "OutboxDispatcher | None" = None
    orchestrator: Any | None = None
    registry: Any | None = None
    config_path: "Path | Any | None" = None
    config_watcher: Any | None = None
