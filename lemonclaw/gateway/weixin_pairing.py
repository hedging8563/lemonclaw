from __future__ import annotations

import asyncio
import hmac
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from lemonclaw.channels.weixin_bridge_runtime import (
    WeixinBridgeError,
    disconnect_weixin,
    get_weixin_pairing_state,
)


def get_weixin_pairing_routes(
    *,
    auth_state: Any | None,
    config_path: Any,
    runtime: Any | None = None,
) -> list[Route]:
    from lemonclaw.gateway.webui.auth import GatewayAuthState

    def _auth_token() -> str | None:
        if isinstance(auth_state, GatewayAuthState):
            return auth_state.token
        return auth_state

    def _require_bearer(request: Request) -> JSONResponse | None:
        token = _auth_token()
        if not token:
            return None
        header = request.headers.get("authorization", "")
        if not hmac.compare_digest(header, f"Bearer {token}"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    async def get_pairing_state(request: Request) -> JSONResponse:
        auth_error = _require_bearer(request)
        if auth_error:
            return auth_error

        from lemonclaw.config.loader import load_config

        config = load_config(config_path)
        try:
            state = await asyncio.to_thread(get_weixin_pairing_state, config.channels.weixin, start_if_needed=False, wait_timeout=5.0)
            return JSONResponse(state)
        except WeixinBridgeError as exc:
            return JSONResponse({"error": str(exc), "status": "error", "running": False}, status_code=400)

    async def start_pairing(request: Request) -> JSONResponse:
        auth_error = _require_bearer(request)
        if auth_error:
            return auth_error

        from lemonclaw.config.loader import load_config, save_config

        try:
            body = await request.json()
        except Exception:
            body = {}

        config = load_config(config_path)
        if not config.channels.weixin.enabled:
            config.channels.weixin.enabled = True
            save_config(config, config_path)
        await _ensure_runtime_channel(config)
        try:
            state = await asyncio.to_thread(
                get_weixin_pairing_state,
                config.channels.weixin,
                start_if_needed=True,
                force=bool(body.get("force")),
                account_id=str(body.get("accountId") or "").strip() or None,
                wait_timeout=20.0,
            )
            return JSONResponse(state)
        except WeixinBridgeError as exc:
            return JSONResponse({"error": str(exc), "status": "error", "running": False}, status_code=400)

    async def repair_pairing(request: Request) -> JSONResponse:
        auth_error = _require_bearer(request)
        if auth_error:
            return auth_error

        from lemonclaw.config.loader import load_config, save_config

        config = load_config(config_path)
        if not config.channels.weixin.enabled:
            config.channels.weixin.enabled = True
            save_config(config, config_path)

        try:
            state = await asyncio.to_thread(
                get_weixin_pairing_state,
                config.channels.weixin,
                start_if_needed=True,
                wait_timeout=5.0,
            )
            if state.get("status") == "connected" or state.get("accounts"):
                await _ensure_runtime_channel(config)
            return JSONResponse(state)
        except WeixinBridgeError as exc:
            return JSONResponse({"error": str(exc), "status": "error", "running": False}, status_code=400)

    async def disconnect_pairing(request: Request) -> JSONResponse:
        auth_error = _require_bearer(request)
        if auth_error:
            return auth_error

        from lemonclaw.config.loader import load_config

        try:
            body = await request.json()
        except Exception:
            body = {}

        config = load_config(config_path)
        try:
            state = await asyncio.to_thread(disconnect_weixin, config.channels.weixin, body.get("accountId"))
            return JSONResponse(state)
        except WeixinBridgeError as exc:
            return JSONResponse({"error": str(exc), "status": "error", "running": False}, status_code=400)

    async def _ensure_runtime_channel(config: Any) -> None:
        channel_manager = getattr(runtime, "channel_manager", None)
        if channel_manager is None or channel_manager.get_channel("weixin") is not None:
            return
        from lemonclaw.channels.weixin import WeixinChannel

        await channel_manager.ensure_channel(
            "weixin",
            WeixinChannel(
                config.channels.weixin,
                channel_manager.bus,
                trigger_runtime=getattr(channel_manager, "trigger_runtime", None),
            ),
        )

    return [
        Route("/api/weixin/pairing", get_pairing_state, methods=["GET"]),
        Route("/api/weixin/pairing", start_pairing, methods=["POST"]),
        Route("/api/weixin/repair", repair_pairing, methods=["POST"]),
        Route("/api/weixin/disconnect", disconnect_pairing, methods=["POST"]),
    ]
