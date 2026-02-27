"""Health check endpoints for K8s liveness/readiness probes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from lemonclaw.channels.manager import ChannelManager

# Populated by server.py at startup
_start_time: float = 0.0
_version: str = "unknown"
_channel_manager: ChannelManager | None = None


def set_context(
    version: str,
    channel_manager: ChannelManager | None = None,
) -> None:
    """Set runtime context for health endpoints."""
    global _start_time, _version, _channel_manager
    _start_time = time.monotonic()
    _version = version
    _channel_manager = channel_manager


async def liveness(request: Request) -> JSONResponse:
    """GET /health — K8s liveness probe. Process alive = 200."""
    return JSONResponse({"status": "ok", "version": _version})


async def readiness(request: Request) -> JSONResponse:
    """GET /readyz — K8s readiness probe.

    Checks IM channel connectivity. Returns 503 if not ready
    (K8s removes from Service endpoints but does NOT kill Pod).
    """
    checks: dict[str, bool] = {}

    if _channel_manager is not None:
        enabled = _channel_manager.enabled_channels
        checks["channels_configured"] = len(enabled) > 0
    else:
        checks["channels_configured"] = False

    ready = all(checks.values())
    status_code = 200 if ready else 503
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=status_code,
    )
