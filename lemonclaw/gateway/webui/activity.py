"""Activity Feed routes: REST history + WebSocket real-time push."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

if TYPE_CHECKING:
    from lemonclaw.bus.activity import ActivityBus
    from lemonclaw.session.manager import SessionManager


def get_activity_routes(
    *,
    activity_bus: ActivityBus,
    session_manager: SessionManager,
    auth_token: str | None = None,
) -> list[Route | WebSocketRoute]:
    """Build Activity Feed routes (REST + WebSocket)."""

    from lemonclaw.gateway.webui.auth import COOKIE_NAME, verify_session_cookie

    def _check_auth(request: Request) -> bool:
        if not auth_token:
            return True
        cookie = request.cookies.get(COOKIE_NAME, "")
        valid, _ = verify_session_cookie(cookie, auth_token)
        return valid

    # ── REST: GET /api/activity/sessions ──────────────────────────────

    async def list_sessions(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return JSONResponse({"error": "Unauthorized"}, 401)

        sessions = []
        for info in session_manager.list_sessions():
            key = info.get("key", "")
            if not key or key.startswith("webui:") or key.startswith("api:") or key.startswith("cron:"):
                continue
            sessions.append({
                "key": key,
                "channel": key.split(":")[0] if ":" in key else "unknown",
                "title": info.get("title", ""),
                "updated_at": info.get("updated_at", ""),
                "message_count": info.get("message_count", 0),
            })
        return JSONResponse({"sessions": sessions})

    # ── REST: GET /api/activity/messages ──────────────────────────────

    async def get_messages(request: Request) -> JSONResponse:
        if not _check_auth(request):
            return JSONResponse({"error": "Unauthorized"}, 401)

        session_key = request.query_params.get("session_key", "")
        if not session_key:
            return JSONResponse({"error": "session_key is required"}, 400)

        try:
            limit = min(int(request.query_params.get("limit", "50")), 200)
        except (ValueError, TypeError):
            limit = 50

        session = session_manager._load(session_key)
        if not session:
            return JSONResponse({"error": "session not found"}, 404)

        messages: list[dict[str, Any]] = []
        for msg in session.messages[-limit:]:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "tool":
                continue  # tool results too verbose

            if role == "assistant" and not content and msg.get("tool_calls"):
                # tool_call message — format as summary
                calls = msg.get("tool_calls", [])
                parts = []
                for tc in calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "?")
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                        first_val = next(iter(args.values()), "")
                        if isinstance(first_val, str) and len(first_val) > 40:
                            first_val = first_val[:40] + "..."
                        parts.append(f'{name}("{first_val}")')
                    except Exception:
                        parts.append(name)
                messages.append({
                    "role": "tool_call",
                    "content": ", ".join(parts),
                    "timestamp": msg.get("timestamp", ""),
                })
                continue

            if role in ("user", "assistant", "system"):
                messages.append({
                    "role": role,
                    "content": content or "",
                    "timestamp": msg.get("timestamp", ""),
                })

        return JSONResponse({"messages": messages})

    # ── WebSocket: /ws/activity ───────────────────────────────────────

    async def ws_activity(websocket: WebSocket) -> None:
        # Auth check before accept
        if auth_token:
            cookie = websocket.cookies.get(COOKIE_NAME, "")
            valid, _ = verify_session_cookie(cookie, auth_token)
            if not valid:
                await websocket.close(code=4001, reason="Unauthorized")
                return

        await websocket.accept()
        queue = activity_bus.subscribe()
        logger.info("Activity WebSocket connected (clients: {})", activity_bus.client_count)

        async def _send_loop():
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        break
                except Exception:
                    break

        async def _recv_loop():
            """Consume client messages to prevent buffer buildup."""
            try:
                while True:
                    await websocket.receive_text()
            except Exception:
                pass

        try:
            await asyncio.gather(_send_loop(), _recv_loop())
        except Exception:
            pass
        finally:
            activity_bus.unsubscribe(queue)
            logger.info("Activity WebSocket disconnected (clients: {})", activity_bus.client_count)

    return [
        Route("/api/activity/sessions", list_sessions, methods=["GET"]),
        Route("/api/activity/messages", get_messages, methods=["GET"]),
        WebSocketRoute("/ws/activity", ws_activity),
    ]
