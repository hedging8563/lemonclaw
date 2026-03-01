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


_NO_CACHE = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


def _json(data: dict, status_code: int = 200) -> JSONResponse:
    """JSONResponse with no-cache headers (prevent CDN caching auth-protected content)."""
    return JSONResponse(data, status_code=status_code, headers=_NO_CACHE)


def _set_cookie(response: Response, cookie_value: str, *, secure: bool = False) -> None:
    response.set_cookie(
        COOKIE_NAME,
        cookie_value,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


def _clear_cookie(response: Response, *, secure: bool = False) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
        secure=secure,
    )


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
    version: str = "unknown",
) -> list[Route]:
    """Build WebUI routes. auth_token=None disables auth (localhost mode)."""

    def _is_secure(request: Request) -> bool:
        """Detect HTTPS from request scheme or X-Forwarded-Proto."""
        if request.url.scheme == "https":
            return True
        return request.headers.get("x-forwarded-proto", "") == "https"

    # ── GET / — serve SPA ────────────────────────────────────────────────

    async def index(request: Request) -> Response:
        try:
            html = _load_index_html()
        except FileNotFoundError:
            return _json({"error": "WebUI not available"}, 404)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    # ── POST /api/auth — login ───────────────────────────────────────────

    async def auth_login(request: Request) -> Response:
        if not auth_token:
            return _json({"ok": True, "auth_required": False})

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        provided = body.get("token", "")
        if not provided or not verify_token(provided, auth_token):
            return _json({"error": "Invalid token"}, 401)

        cookie = create_session_cookie(auth_token)
        resp = _json({"ok": True})
        _set_cookie(resp, cookie, secure=_is_secure(request))
        return resp

    # ── DELETE /api/auth — logout ────────────────────────────────────────

    async def auth_logout(request: Request) -> Response:
        resp = _json({"ok": True})
        _clear_cookie(resp, secure=_is_secure(request))
        return resp

    # ── GET /api/auth/check — probe auth state ────────────────────────

    async def auth_check(request: Request) -> Response:
        if not auth_token:
            return _json({"ok": True, "auth_required": False})
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return _json({"ok": False, "auth_required": True}, 401)
        valid, _ = verify_session_cookie(cookie, auth_token)
        if valid:
            return _json({"ok": True, "auth_required": True})
        return _json({"ok": False, "auth_required": True}, 401)

    # ── Auth middleware helper ────────────────────────────────────────────

    def _require_auth(request: Request) -> tuple[bool, Response | None]:
        """Returns (ok, error_response). On success, ok=True and response=None."""
        if not auth_token:
            return True, None
        valid, refreshed = _check_webui_auth(request, auth_token)
        if not valid:
            return False, _json({"error": "Unauthorized"}, 401)
        # Store refreshed cookie for the handler to set
        request.state.refreshed_cookie = refreshed
        return True, None

    def _maybe_refresh_cookie(request: Request, response: Response) -> None:
        cookie = getattr(request.state, "refreshed_cookie", None)
        if cookie:
            _set_cookie(response, cookie, secure=_is_secure(request))

    # ── POST /api/chat/stream — SSE streaming ────────────────────────────

    async def chat_stream(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        message = body.get("message", "").strip()
        if not message:
            return _json({"error": "Empty message"}, 400)

        session_key = body.get("session_key", "webui:default")
        # Enforce webui: prefix — prevent accessing other channel sessions
        if not session_key.startswith("webui:"):
            session_key = f"webui:{session_key}"

        # Write model override to session metadata before processing
        model = body.get("model")
        if model:
            session = session_manager.get_or_create(session_key)
            session.metadata["current_model"] = model
            session_manager.save(session)

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
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if item is None:
                        break
                    yield item
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        from starlette.responses import StreamingResponse

        resp = StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, private",
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
        resp = _json({"sessions": webui_sessions})
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
            return _json({"error": "Forbidden"}, 403)

        deleted = session_manager.delete_session(key)
        resp = _json({"deleted": deleted})
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
        resp = _json({"models": models, "current": current})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── GET /api/sessions/{key}/messages — session history ─────────────

    async def get_session_messages(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        key = request.path_params["key"]
        if not key.startswith("webui:"):
            return _json({"error": "Forbidden"}, 403)

        session = session_manager.get_or_create(key)
        # Return messages with role and content only (safe for frontend)
        messages = []
        for m in session.messages:
            role = m.get("role")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                # Skip tool_calls-only assistant messages (content is empty/null)
                if isinstance(content, list):
                    # Multimodal content — extract text parts
                    content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
                if content:
                    messages.append({"role": role, "content": content})

        resp = _json({"messages": messages})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── GET /api/info — instance status + version + session usage ──────

    async def get_info(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        import time as _time
        data: dict = {"version": version}

        # Instance uptime
        if usage_tracker:
            data.update(usage_tracker.get_instance_summary())

        # Per-session usage if ?session=key
        session_key = request.query_params.get("session")
        if session_key and usage_tracker:
            if not session_key.startswith("webui:"):
                session_key = f"webui:{session_key}"
            session = session_manager.get_or_create(session_key)
            data["session_usage"] = usage_tracker.get_session_summary(session.metadata)

        resp = _json(data)
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── Assemble routes ──────────────────────────────────────────────────

    return [
        Route("/", index, methods=["GET"]),
        Route("/api/auth", auth_login, methods=["POST"]),
        Route("/api/auth", auth_logout, methods=["DELETE"]),
        Route("/api/auth/check", auth_check, methods=["GET"]),
        Route("/api/chat/stream", chat_stream, methods=["POST"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/sessions/{key:path}/messages", get_session_messages, methods=["GET"]),
        Route("/api/sessions/{key:path}", delete_session, methods=["DELETE"]),
        Route("/api/models", list_models, methods=["GET"]),
        Route("/api/info", get_info, methods=["GET"]),
    ]
