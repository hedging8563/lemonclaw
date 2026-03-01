"""WebUI route handlers — closure factory pattern matching server.py."""

from __future__ import annotations

import asyncio
import json
import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from lemonclaw.gateway.webui.auth import (
    COOKIE_NAME,
    create_session_cookie,
    verify_session_cookie,
    verify_token,
)
from lemonclaw.providers.catalog import MODEL_CATALOG

if TYPE_CHECKING:
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.session.manager import SessionManager
    from lemonclaw.agent.usage import UsageTracker


def _check_webui_auth(
    request: Request, auth_token: str
) -> tuple[bool, str | None]:
    """Check cookie auth. Returns (valid, refreshed_cookie)."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return False, None
    return verify_session_cookie(cookie, auth_token)


def _set_cookie(response: Response, cookie_value: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        cookie_value,
        httponly=True,
        samesite="strict",
        secure=False,  # Allow HTTP for localhost dev
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# ── Static file serving ─────────────────────────────────────────────────────

_INDEX_HTML: str | None = None


def _load_index_html() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is not None:
        return _INDEX_HTML

    # Try importlib.resources first (installed package)
    try:
        ref = importlib.resources.files("lemonclaw.gateway.webui.static").joinpath("index.html")
        _INDEX_HTML = ref.read_text(encoding="utf-8")
        return _INDEX_HTML
    except Exception:
        pass

    # Fallback: relative path (development)
    dev_path = Path(__file__).parent / "static" / "index.html"
    if dev_path.exists():
        _INDEX_HTML = dev_path.read_text(encoding="utf-8")
        return _INDEX_HTML

    raise FileNotFoundError("WebUI index.html not found")


# ── Route factory ────────────────────────────────────────────────────────────


def get_webui_routes(
    *,
    auth_token: str | None,
    agent_loop: AgentLoop,
    session_manager: SessionManager,
    usage_tracker: UsageTracker | None = None,
) -> list[Route]:
    """Build WebUI routes. auth_token=None disables auth (localhost mode)."""

    # ── GET / — serve SPA ────────────────────────────────────────────────

    async def index(request: Request) -> Response:
        try:
            html = _load_index_html()
        except FileNotFoundError:
            return JSONResponse({"error": "WebUI not available"}, status_code=404)
        return HTMLResponse(html)

    # ── POST /api/auth — login ───────────────────────────────────────────

    async def auth_login(request: Request) -> Response:
        if not auth_token:
            # No auth configured → localhost mode, auto-login
            return JSONResponse({"ok": True})

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        provided = body.get("token", "")
        if not provided or not verify_token(provided, auth_token):
            return JSONResponse({"error": "Invalid token"}, status_code=401)

        cookie = create_session_cookie(auth_token)
        resp = JSONResponse({"ok": True})
        _set_cookie(resp, cookie)
        return resp

    # ── DELETE /api/auth — logout ────────────────────────────────────────

    async def auth_logout(request: Request) -> Response:
        resp = JSONResponse({"ok": True})
        _clear_cookie(resp)
        return resp

    # ── Auth middleware helper ────────────────────────────────────────────

    def _require_auth(request: Request) -> tuple[bool, Response | None]:
        """Returns (ok, error_response). On success, ok=True and response=None."""
        if not auth_token:
            return True, None
        valid, refreshed = _check_webui_auth(request, auth_token)
        if not valid:
            return False, JSONResponse({"error": "Unauthorized"}, status_code=401)
        # Store refreshed cookie for the handler to set
        request.state.refreshed_cookie = refreshed
        return True, None

    def _maybe_refresh_cookie(request: Request, response: Response) -> None:
        cookie = getattr(request.state, "refreshed_cookie", None)
        if cookie:
            _set_cookie(response, cookie)

    # ── POST /api/chat/stream — SSE streaming ────────────────────────────

    async def chat_stream(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        message = body.get("message", "").strip()
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        session_key = body.get("session_key", "webui:default")
        # Enforce webui: prefix — prevent accessing other channel sessions
        if not session_key.startswith("webui:"):
            session_key = f"webui:{session_key}"
        model = body.get("model")

        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            event = {"type": "tool_hint" if tool_hint else "content", "data": content}
            await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")

        async def run_agent() -> None:
            try:
                # If model specified, temporarily set it via session metadata
                final = await agent_loop.process_direct(
                    content=message,
                    session_key=session_key,
                    channel="webui",
                    chat_id="webui",
                    on_progress=on_progress,
                )
                # Send final response
                event = {"type": "done", "data": final}
                await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
            except Exception as exc:
                logger.error("WebUI chat error: {}", exc)
                event = {"type": "error", "data": str(exc)}
                await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
            finally:
                await queue.put(None)  # Sentinel

        task = asyncio.create_task(run_agent())

        async def event_generator():
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield item
            finally:
                if not task.done():
                    task.cancel()

        from starlette.responses import StreamingResponse

        resp = StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── GET /api/sessions — list sessions ────────────────────────────────

    async def list_sessions(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        sessions = session_manager.list_sessions()
        # Filter to webui sessions only
        webui_sessions = [s for s in sessions if s.get("key", "").startswith("webui:")]
        resp = JSONResponse({"sessions": webui_sessions})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── DELETE /api/sessions/{key} — delete session ──────────────────────

    async def delete_session(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        key = request.path_params["key"]
        # Security: only allow deleting webui sessions
        if not key.startswith("webui:"):
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        deleted = session_manager.delete_session(key)
        resp = JSONResponse({"deleted": deleted})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── GET /api/models — list available models ──────────────────────────

    async def list_models(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        models = [
            {"id": m.id, "label": m.label, "tier": m.tier, "description": m.description}
            for m in MODEL_CATALOG
            if not m.hidden
        ]
        current = agent_loop.model if hasattr(agent_loop, "model") else ""
        resp = JSONResponse({"models": models, "current": current})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── Assemble routes ──────────────────────────────────────────────────

    return [
        Route("/", index, methods=["GET"]),
        Route("/api/auth", auth_login, methods=["POST"]),
        Route("/api/auth", auth_logout, methods=["DELETE"]),
        Route("/api/chat/stream", chat_stream, methods=["POST"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/sessions/{key:path}", delete_session, methods=["DELETE"]),
        Route("/api/models", list_models, methods=["GET"]),
    ]
