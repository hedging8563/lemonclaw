"""Health check endpoints for K8s liveness/readiness probes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

from lemonclaw.gateway.runtime_state import derive_runtime_state_view, load_runtime_state

if TYPE_CHECKING:
    from lemonclaw.channels.manager import ChannelManager

# Populated by server.py at startup
_start_time: float = 0.0
_version: str = "unknown"
_channel_manager: ChannelManager | None = None
_config_path: Path | None = None


def set_context(
    version: str,
    channel_manager: ChannelManager | None = None,
    config_path: Path | None = None,
) -> None:
    """Set runtime context for health endpoints."""
    global _start_time, _version, _channel_manager, _config_path
    _start_time = time.monotonic()
    _version = version
    _channel_manager = channel_manager
    _config_path = Path(config_path) if config_path is not None else None


def _channel_status_snapshot() -> dict[str, dict[str, object]]:
    if _channel_manager is None or not hasattr(_channel_manager, "get_channel_status"):
        return {}
    try:
        return _channel_manager.get_channel_status()
    except Exception:
        return {}


def _configured_channels_are_usable(channel_status: dict[str, dict[str, object]]) -> bool:
    configured_channels = [
        name
        for name, status in channel_status.items()
        if bool(status.get("configured_enabled"))
    ]
    if not configured_channels:
        return False

    for name in configured_channels:
        status = channel_status.get(name, {})
        if not bool(status.get("configured_complete", True)):
            return False
        if not bool(status.get("registered", False)):
            return False
        if not bool(status.get("available", False)):
            return False
        if not bool(status.get("running", False)):
            return False
        if str(status.get("error") or "").strip():
            return False
    return True


def _restart_state_is_healthy() -> bool:
    if _config_path is None:
        return True
    state = derive_runtime_state_view(load_runtime_state(_config_path))
    return bool(state.get("restart_state_healthy"))


async def liveness(request: Request) -> JSONResponse:
    """GET /health — K8s liveness probe. Process alive = 200."""
    return JSONResponse({"status": "ok", "version": _version})


async def readiness(request: Request) -> JSONResponse:
    """GET /readyz — K8s readiness probe.

    Checks channel availability and persisted restart state. Returns 503 if
    not ready (K8s removes from Service endpoints but does NOT kill Pod).
    """
    channel_status = _channel_status_snapshot()
    checks: dict[str, bool] = {
        "channels_configured": any(bool(status.get("configured_enabled")) for status in channel_status.values()),
        "channels_usable": _configured_channels_are_usable(channel_status),
        "restart_state_healthy": _restart_state_is_healthy(),
    }

    ready = all(checks.values())
    status_code = 200 if ready else 503
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=status_code,
    )
