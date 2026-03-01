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
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from lemonclaw.gateway.health import liveness, readiness, set_context

if TYPE_CHECKING:
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.channels.manager import ChannelManager
    from lemonclaw.session.manager import SessionManager
    from lemonclaw.telemetry.usage import UsageTracker


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


def _build_usage_handler(
    auth_token: str | None,
    usage_tracker: UsageTracker | None,
    session_manager: SessionManager | None,
):
    """Return a handler for GET /api/usage (token-protected)."""

    async def usage_handler(request: Request) -> JSONResponse:
        if auth_token:
            header = request.headers.get("authorization", "")
            if header != f"Bearer {auth_token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        if not usage_tracker:
            return JSONResponse({"error": "usage tracking not available"}, status_code=503)

        # Instance-level summary
        data: dict[str, Any] = usage_tracker.get_instance_summary()

        # Optional: per-session detail
        session_key = request.query_params.get("session")
        if session_key and session_manager:
            # Use _load to avoid creating empty sessions from arbitrary query params
            session = session_manager._load(session_key)
            if session:
                data["session"] = {
                    "key": session_key,
                    **usage_tracker.get_session_summary(session.metadata),
                }
            else:
                data["session"] = {"key": session_key, "error": "not found"}
        elif session_manager:
            # List all sessions with usage data (from metadata in JSONL)
            sessions_usage = []
            for info in session_manager.list_sessions():
                key = info.get("key", "")
                if not key:
                    continue
                s = session_manager._load(key)
                if not s:
                    continue
                stats = s.metadata.get("usage_stats")
                if stats and stats.get("total_tokens", 0) > 0:
                    sessions_usage.append({
                        "key": key,
                        **usage_tracker.get_session_summary(s.metadata),
                    })
            if sessions_usage:
                data["sessions"] = sessions_usage

        return JSONResponse(data)

    return usage_handler


def _build_chat_handler(
    auth_token: str | None,
    agent_loop: AgentLoop | None,
):
    """Return a handler for POST /api/chat (token-protected, for testing)."""

    async def chat_handler(request: Request) -> JSONResponse:
        if auth_token:
            header = request.headers.get("authorization", "")
            if header != f"Bearer {auth_token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        if not agent_loop:
            return JSONResponse({"error": "agent loop not available"}, status_code=503)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        message = body.get("message", "").strip()
        if not message:
            return JSONResponse({"error": "message is required"}, status_code=400)

        session_key = body.get("session", "api:test")
        timeout = min(body.get("timeout", 120), 300)

        try:
            response = await asyncio.wait_for(
                agent_loop.process_direct(
                    content=message,
                    session_key=session_key,
                    channel="api",
                    chat_id="test",
                ),
                timeout=timeout,
            )
            return JSONResponse({"response": response, "session": session_key})
        except asyncio.TimeoutError:
            return JSONResponse({"error": f"timeout after {timeout}s"}, status_code=504)
        except Exception as e:
            logger.exception("Chat API error")
            return JSONResponse({"error": str(e)}, status_code=500)

    return chat_handler


def _build_wecom_webhook_handler(channel_manager: ChannelManager | None):
    """Return handlers for GET+POST /webhook/wecom (WeCom callback)."""

    def _get_wecom_channel():
        if not channel_manager:
            return None
        ch = channel_manager.get_channel("wecom")
        if ch is None:
            return None
        # Import here to avoid circular imports at module level
        from lemonclaw.channels.wecom import WeComChannel

        return ch if isinstance(ch, WeComChannel) else None

    async def wecom_verify(request: Request) -> PlainTextResponse:
        """GET /webhook/wecom — URL verification for WeCom admin console."""
        wecom = _get_wecom_channel()
        if not wecom:
            return PlainTextResponse("wecom channel not enabled", status_code=404)

        params = dict(request.query_params)
        result = await wecom.handle_verify(params)
        if result is None:
            return PlainTextResponse("verification failed", status_code=403)
        return PlainTextResponse(result)

    async def wecom_callback(request: Request) -> PlainTextResponse:
        """POST /webhook/wecom — incoming message callback."""
        wecom = _get_wecom_channel()
        if not wecom:
            return PlainTextResponse("wecom channel not enabled", status_code=404)

        body = (await request.body()).decode("utf-8")
        params = dict(request.query_params)
        result = await wecom.handle_callback(params, body)
        if result is None:
            return PlainTextResponse("callback error", status_code=400)
        return PlainTextResponse(result)

    return wecom_verify, wecom_callback


def create_app(
    *,
    auth_token: str | None = None,
    channel_manager: ChannelManager | None = None,
    version: str = "unknown",
    model: str = "",
    instance_id: str = "",
    usage_tracker: UsageTracker | None = None,
    session_manager: SessionManager | None = None,
    agent_loop: AgentLoop | None = None,
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
        Route("/api/usage", _build_usage_handler(auth_token, usage_tracker, session_manager), methods=["GET"]),
        Route("/api/chat", _build_chat_handler(auth_token, agent_loop), methods=["POST"]),
    ]

    # WeCom webhook routes (no auth_token — WeCom uses its own signature verification)
    wecom_verify, wecom_callback = _build_wecom_webhook_handler(channel_manager)
    routes.append(Route("/webhook/wecom", wecom_verify, methods=["GET"]))
    routes.append(Route("/webhook/wecom", wecom_callback, methods=["POST"]))

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
