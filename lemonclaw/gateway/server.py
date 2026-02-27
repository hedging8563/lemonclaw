"""Starlette ASGI gateway server with health endpoints.

Runs alongside the agent loop and channel manager inside the
``lemonclaw gateway`` command.  Provides:

- GET /health   — liveness probe (always 200 if process alive)
- GET /readyz   — readiness probe (checks channel connectivity)
- GET /api/status — detailed instance status (requires auth_token)
"""

from __future__ import annotations

import asyncio
import signal
import time
from typing import TYPE_CHECKING, Any

import uvicorn
from loguru import logger
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lemonclaw.gateway.health import liveness, readiness, set_context

if TYPE_CHECKING:
    from lemonclaw.channels.manager import ChannelManager


def _build_status_handler(
    auth_token: str | None,
    channel_manager: ChannelManager | None,
    extra: dict[str, Any] | None = None,
):
    """Return a handler for GET /api/status (token-protected)."""

    async def status_handler(request: Request) -> JSONResponse:
        if auth_token:
            header = request.headers.get("authorization", "")
            if header != f"Bearer {auth_token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        data: dict[str, Any] = {
            "uptime_s": round(time.monotonic() - (extra or {}).get("start_time", 0), 1),
        }
        if channel_manager:
            data["channels"] = channel_manager.enabled_channels
        if extra:
            for k in ("version", "model", "instance_id"):
                if k in extra:
                    data[k] = extra[k]
        return JSONResponse(data)

    return status_handler


def create_app(
    *,
    auth_token: str | None = None,
    channel_manager: ChannelManager | None = None,
    version: str = "unknown",
    model: str = "",
    instance_id: str = "",
) -> Starlette:
    """Build the Starlette ASGI application."""
    start_time = time.monotonic()
    set_context(version=version, channel_manager=channel_manager)

    extra = {
        "start_time": start_time,
        "version": version,
        "model": model,
        "instance_id": instance_id,
    }

    routes = [
        Route("/health", liveness, methods=["GET"]),
        Route("/readyz", readiness, methods=["GET"]),
        Route("/api/status", _build_status_handler(auth_token, channel_manager, extra), methods=["GET"]),
    ]
    return Starlette(routes=routes)


class GatewayServer:
    """Manages the uvicorn server lifecycle for graceful shutdown.

    Usage::

        server = GatewayServer(app, host="localhost", port=18789)
        # In asyncio.gather:
        await server.serve()
        # To stop:
        await server.shutdown()
    """

    def __init__(self, app: Starlette, host: str, port: int):
        self.app = app
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None

    async def serve(self) -> None:
        """Start uvicorn and block until shutdown is requested."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        logger.info("Gateway HTTP server listening on {}:{}", self.host, self.port)
        await self._server.serve()

    async def shutdown(self) -> None:
        """Signal uvicorn to stop accepting connections."""
        if self._server:
            self._server.should_exit = True


class GracefulShutdown:
    """Coordinates SIGTERM graceful shutdown sequence.

    Shutdown order (per plan):
    1. Stop accepting new channel messages
    2. Drain in-progress LLM streaming (max 15s)
    3. Close HTTP server
    4. Exit
    """

    DRAIN_TIMEOUT = 15  # seconds

    def __init__(self) -> None:
        self._shutdown_event = asyncio.Event()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    def register_signals(self) -> None:
        """Register SIGTERM/SIGINT handlers on the running event loop."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

    def _handle_signal(self, sig: signal.Signals) -> None:
        logger.info("Received {} — initiating graceful shutdown", sig.name)
        self._shutdown_event.set()

    async def wait(self) -> None:
        """Block until a shutdown signal is received."""
        await self._shutdown_event.wait()

    async def execute(
        self,
        *,
        channels: Any | None = None,
        agent: Any | None = None,
        cron: Any | None = None,
        heartbeat: Any | None = None,
        http_server: GatewayServer | None = None,
    ) -> None:
        """Run the full shutdown sequence."""
        logger.info("Shutdown phase 1: stopping channels")
        if channels:
            await channels.stop_all()

        logger.info("Shutdown phase 2: draining LLM streams (max {}s)", self.DRAIN_TIMEOUT)
        if agent:
            agent.stop()
            await agent.close_mcp()

        if cron:
            cron.stop()
        if heartbeat:
            heartbeat.stop()

        logger.info("Shutdown phase 3: closing HTTP server")
        if http_server:
            await http_server.shutdown()

        logger.info("Shutdown complete")
