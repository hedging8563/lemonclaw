"""WebUI route handlers — closure factory pattern matching server.py."""

from __future__ import annotations

import asyncio
import base64
import json
import importlib.resources
import mimetypes
import tempfile
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from lemonclaw.gateway.webui.auth import (
    COOKIE_NAME,
    create_session_cookie,
    verify_session_cookie,
    verify_token,
)
from lemonclaw.providers.catalog import MODEL_CATALOG
from lemonclaw.gateway.webui.message_schema import extract_message_media_paths, serialize_ui_message

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
        logger.debug("importlib.resources load failed, trying filesystem fallback")

    # Fallback: relative path (development)
    dev_path = Path(__file__).parent / "static" / "index.html"
    if dev_path.exists():
        _INDEX_HTML = dev_path.read_text(encoding="utf-8")
        return _INDEX_HTML

    raise FileNotFoundError("WebUI index.html not found")


def _get_static_file(name: str) -> bytes | None:
    """Load a static file from resources or filesystem fallback."""
    try:
        ref = importlib.resources.files("lemonclaw.gateway.webui.static").joinpath(name)
        return ref.read_bytes()
    except Exception:
        pass

    dev_path = Path(__file__).parent / "static" / name
    if dev_path.exists():
        return dev_path.read_bytes()
    return None


# ── Session message helpers ─────────────────────────────────────────────────


def _visible_ui_messages(session, *, session_key: str | None = None) -> list[dict]:
    messages = []
    for m in session.messages:
        role = m.get("role")
        if role == "tool":
            continue
        if role in ("user", "assistant", "system", "tool_call"):
            messages.append(serialize_ui_message(m, session_key=session_key))
    return messages


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

    # ── GET /logo-icon.svg — serve bot avatar & favicon ──────────────────

    async def logo_icon(request: Request) -> Response:
        content = _get_static_file("logo-icon.svg")
        if not content:
            return Response("Not Found", status_code=404)
        return Response(content, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})

    async def vite_icon(request: Request) -> Response:
        content = _get_static_file("vite.svg")
        if not content:
            return Response("Not Found", status_code=404)
        return Response(content, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})

    async def logo_64_png(request: Request) -> Response:
        # 1. Try static dir (if packaged)
        content = _get_static_file("logo-64.png")
        if not content:
            # 2. Try root assets dir (development)
            from pathlib import Path
            asset_path = Path(agent_loop.workspace) / "assets" / "logo-64.png"
            if asset_path.exists():
                content = asset_path.read_bytes()
        
        if not content:
            return Response("Not Found", status_code=404)
        return Response(content, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

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

    # ── Async session title generation ────────────────────────────────────

    def _extract_session_title(first_message: str, max_len: int = 25) -> str:
        """Extract a clean title from the first message — no LLM, instant."""
        import re
        text = first_message.strip()
        # Strip markdown/URLs/mentions
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'[#*_`~>\[\]()]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return first_message[:max_len].strip() or "New Chat"
        # Take first line only
        text = text.split('\n')[0].strip()
        if len(text) <= max_len:
            return text
        # Smart break: prefer word/CJK boundary
        truncated = text[:max_len]
        # For CJK-heavy text, just cut
        cjk_count = sum(1 for c in truncated if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
        if cjk_count > len(truncated) * 0.3:
            return truncated.rstrip() + "…"
        # For latin text, break at last space
        last_space = truncated.rfind(' ')
        if last_space > max_len // 2:
            return truncated[:last_space].rstrip() + "…"
        return truncated.rstrip() + "…"

    def _set_session_title(session_key: str, first_message: str) -> None:
        """Set session title from first message — instant, no LLM."""
        session = session_manager.get_or_create(session_key)
        if session.metadata.get("title"):
            return
        session.metadata["title"] = _extract_session_title(first_message)
        session_manager.save(session)

    # ── POST /api/chat/stream — SSE streaming ────────────────────────────

    # 7.1: Temp directory for uploaded files
    _upload_dir = Path(tempfile.mkdtemp(prefix="lemonclaw_uploads_"))
    _session_media_grants: dict[str, dict[str, Any]] = {}
    _SESSION_MEDIA_GRANT_TTL_S = 6 * 60 * 60
    _SESSION_MEDIA_GRANT_MAX = 512

    def _touch_session_media_grants(session_key: str, paths: list[str] | None = None) -> None:
        now = time.time()
        entry = _session_media_grants.setdefault(session_key, {"paths": set(), "last_access": now})
        entry["last_access"] = now
        if paths:
            entry["paths"].update(paths)

    def _cleanup_session_media_grants() -> None:
        now = time.time()
        expired = [k for k, v in _session_media_grants.items() if now - float(v.get("last_access", now)) > _SESSION_MEDIA_GRANT_TTL_S]
        for key in expired:
            _session_media_grants.pop(key, None)
        if len(_session_media_grants) > _SESSION_MEDIA_GRANT_MAX:
            extra = len(_session_media_grants) - _SESSION_MEDIA_GRANT_MAX
            oldest = sorted(_session_media_grants.items(), key=lambda item: float(item[1].get("last_access", 0)))[:extra]
            for key, _ in oldest:
                _session_media_grants.pop(key, None)

    def _path_allowed_for_session(file_path: Path, session_key: str) -> bool:
        _cleanup_session_media_grants()
        entry = _session_media_grants.get(session_key)
        if entry and str(file_path) in entry.get("paths", set()):
            _touch_session_media_grants(session_key)
            return True
        if not session_manager:
            return False
        session = session_manager._load(session_key)
        if not session:
            return False
        for msg in session.messages:
            paths = extract_message_media_paths(msg)
            if str(file_path) in paths:
                _touch_session_media_grants(session_key, paths)
                return True
        return False

    def _cleanup_uploads():
        """Remove uploaded files older than 1 hour."""
        if not _upload_dir.exists():
            return
        cutoff = time.time() - 3600
        for f in _upload_dir.iterdir():
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

    _media_dir = Path.home() / ".lemonclaw" / "media"

    async def get_media(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        raw_path = request.query_params.get("path", "").strip()
        if not raw_path:
            return _json({"error": "path is required"}, 400)

        try:
            file_path = Path(raw_path).expanduser().resolve(strict=True)
        except FileNotFoundError:
            return _json({"error": "file not found"}, 404)
        except OSError:
            return _json({"error": "invalid path"}, 400)

        upload_root = _upload_dir.resolve()
        try:
            if file_path == upload_root or upload_root in file_path.parents:
                media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
                resp = FileResponse(file_path, media_type=media_type, filename=file_path.name, headers={"Cache-Control": "private, max-age=300"})
                _maybe_refresh_cookie(request, resp)
                return resp
        except RuntimeError:
            return _json({"error": "access denied"}, 403)

        session_key = request.query_params.get("session_key", "").strip()
        if not session_key or not _path_allowed_for_session(file_path, session_key):
            return _json({"error": "access denied"}, 403)

        media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        resp = FileResponse(file_path, media_type=media_type, filename=file_path.name, headers={"Cache-Control": "private, max-age=300"})
        _maybe_refresh_cookie(request, resp)
        return resp

    async def upload_file(request: Request) -> Response:
        """7.1: Accept base64-encoded file, save to temp dir, return path."""
        _cleanup_uploads()

        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        data_url = body.get("data", "")
        filename = body.get("filename", "upload")

        if not data_url:
            return _json({"error": "No data"}, 400)

        # Parse data URL: data:image/png;base64,xxxxx
        if data_url.startswith("data:"):
            header, b64 = data_url.split(",", 1) if "," in data_url else ("", data_url)
        else:
            b64 = data_url

        # 10MB file ≈ 13.4MB base64
        if len(b64) > 14 * 1024 * 1024:
            return _json({"error": "File too large (max 10MB)"}, 400)

        try:
            raw = base64.b64decode(b64)
        except Exception:
            return _json({"error": "Invalid base64"}, 400)

        # Limit: 10MB
        if len(raw) > 10 * 1024 * 1024:
            return _json({"error": "File too large (max 10MB)"}, 400)

        # Save with unique name
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")[:60] or "file"
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        path = _upload_dir / unique_name
        path.write_bytes(raw)

        resp = _json({"path": str(path), "size": len(raw)})
        _maybe_refresh_cookie(request, resp)
        return resp

    async def chat_stream(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        message = body.get("message", "").strip()
        media_files: list[str] = body.get("media", [])  # 7.1: list of temp file paths
        # Validate media paths are within upload dir (prevent path traversal)
        if media_files:
            media_files = [
                p for p in media_files
                if Path(p).resolve().parent == _upload_dir.resolve() and Path(p).is_file()
            ]
        if not message and not media_files:
            return _json({"error": "Empty message"}, 400)

        user_timezone = body.get("timezone", "")

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

        async def on_progress(content: str, *, tool_hint: bool = False,
                              thinking: bool = False, tool_start: bool = False,
                              tool_result: bool = False) -> None:
            if thinking:
                etype = "thinking"
            elif tool_hint:
                etype = "tool_hint"
            elif tool_start:
                etype = "tool_start"
            elif tool_result:
                etype = "tool_result"
            else:
                etype = "content"
            event = {"type": etype, "data": content}
            await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")

        async def on_chunk(content: str, *, first: bool = False) -> None:
            event = {"type": "content", "data": content}
            await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")

        async def run_agent() -> None:
            try:
                # If model specified, temporarily set it via session metadata
                async def outbound_sink(out_msg):
                    if out_msg.media:
                        _touch_session_media_grants(session_key, list(out_msg.media))
                    event = {"type": "outbound", "data": serialize_ui_message({"role": "assistant", "content": out_msg.content, "media": list(out_msg.media or [])}, session_key=session_key)}
                    await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")

                final = await agent_loop.process_direct(
                    content=message,
                    session_key=session_key,
                    channel="webui",
                    chat_id="webui",
                    on_progress=on_progress,
                    on_chunk=on_chunk,
                    metadata={"timezone": user_timezone} if user_timezone else None,
                    media=media_files or None,
                    outbound_sink=outbound_sink,
                )
                # Send final response
                event = {"type": "done", "data": serialize_ui_message({"role": "assistant", "content": final}, session_key=session_key)}
                await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
                # Set title for new sessions (instant, no LLM)
                _set_session_title(session_key, message)
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
        # Filter to webui sessions only (model already included from list_sessions)
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

    # ── PATCH /api/sessions/{key} — update session metadata ────────────

    async def update_session(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        key = request.path_params["key"]
        if not key.startswith("webui:"):
            return _json({"error": "Forbidden"}, 403)

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        session = session_manager.get_or_create(key)
        if not session:
            return _json({"error": "Session not found"}, 404)
        if "title" in body:
            title = str(body["title"]).strip()[:60]
            if title:
                session.metadata["title"] = title
        # 6.3: Per-session system prompt override
        if "system_prompt_override" in body:
            sp = str(body["system_prompt_override"]).strip()[:4000]
            if sp:
                session.metadata["system_prompt_override"] = sp
            else:
                session.metadata.pop("system_prompt_override", None)
        session_manager.save(session)
        resp = _json({"ok": True})
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
        # Read user's configured default model from config.json (without env overlay)
        # so DEFAULT_MODEL env var doesn't override the user's choice in WebUI.
        current = ""
        try:
            from lemonclaw.config.loader import get_config_path
            _cfg_path = get_config_path()
            if _cfg_path.exists():
                import json as _json_mod
                with open(_cfg_path, encoding="utf-8") as f:
                    raw = _json_mod.load(f)
                current = raw.get("agents", {}).get("defaults", {}).get("model", "")
        except Exception:
            logger.debug("Failed to read current model from config")
        if not current:
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

        session = session_manager._load(key)
        if not session:
            resp = _json({"messages": []})
            _maybe_refresh_cookie(request, resp)
            return resp

        resp = _json({
            "messages": _visible_ui_messages(session, session_key=key),
            "system_prompt_override": session.metadata.get("system_prompt_override", ""),
        })
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── GET /api/sessions/{key}/export — export session as md or json ──

    async def export_session(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        key = request.path_params["key"]
        if not key.startswith("webui:"):
            return _json({"error": "Forbidden"}, 403)

        session = session_manager._load(key)
        if not session:
            return _json({"error": "Session not found"}, 404)

        fmt = request.query_params.get("format", "md")
        title = session.metadata.get("title", key)

        # Collect user/assistant messages
        turns = []
        for m in session.messages:
            role = m.get("role")
            content = m.get("content", "")
            if role in ("user", "assistant") and content:
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
                if content:
                    turns.append({"role": role, "content": content})

        if fmt == "json":
            body = json.dumps({"title": title, "messages": turns}, ensure_ascii=False, indent=2)
            media = "application/json"
            ext = "json"
        else:
            lines = [f"# {title}\n"]
            for t in turns:
                label = "**User**" if t["role"] == "user" else "**Assistant**"
                lines.append(f"{label}:\n\n{t['content']}\n\n---\n")
            body = "\n".join(lines)
            media = "text/markdown"
            ext = "md"

        safe_title = "".join(c for c in title if c.isalnum() or c in " _-")[:40].strip() or "chat"
        # RFC 5987: use filename* for non-ASCII titles, ASCII fallback for filename
        from urllib.parse import quote
        ascii_fallback = "".join(c for c in safe_title if ord(c) < 128) or "chat"
        encoded_title = quote(safe_title)
        disposition = f'attachment; filename="{ascii_fallback}.{ext}"; filename*=UTF-8\'\'{encoded_title}.{ext}'
        resp = Response(
            content=body.encode("utf-8"),
            media_type=media,
            headers={
                "Content-Disposition": disposition,
            },
        )
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── WebSocket: /ws/session ─────────────────────────────────────────────

    async def ws_session(websocket: WebSocket) -> None:
        if auth_token:
            cookie = websocket.cookies.get(COOKIE_NAME, "")
            valid, _ = verify_session_cookie(cookie, auth_token)
            if not valid:
                await websocket.close(code=4001, reason="Unauthorized")
                return

        session_key = (websocket.query_params.get("session_key") or "").strip()
        if not session_key:
            await websocket.accept()
            await websocket.close(code=4400, reason="session_key is required")
            return
        if session_key.startswith(("api:", "cron:")):
            await websocket.accept()
            await websocket.close(code=4403, reason="access denied")
            return

        known_count_raw = websocket.query_params.get("known_count")
        try:
            known_count = max(int(known_count_raw or "0"), 0)
        except (TypeError, ValueError):
            known_count = 0

        await websocket.accept()

        last_version = -1
        try:
            while True:
                session = session_manager._load(session_key)
                current_version = session.version if session else -1
                if current_version != last_version:
                    visible = _visible_ui_messages(session, session_key=session_key) if session else []
                    if len(visible) > known_count:
                        payload = {
                            "type": "messages",
                            "session_key": session_key,
                            "messages": visible[known_count:],
                            "count": len(visible),
                            "version": current_version,
                        }
                        await websocket.send_text(json.dumps(payload, ensure_ascii=False))
                        known_count = len(visible)
                    last_version = current_version

                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
        except Exception:
            try:
                await websocket.close()
            except Exception:
                pass

    # ── 9.2: Memory REST API ─────────────────────────────────────────────

    from lemonclaw.agent.memory import MemoryStore
    _memory = MemoryStore(agent_loop.workspace)

    async def get_memory(request: Request) -> Response:
        """9.2: Return all memory layers."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        core = _memory.read_core()
        long_term = _memory.read_long_term()
        today = _memory.today.read()

        # Parse history entries
        history_entries = []
        if _memory.history_file.exists():
            text = _memory.history_file.read_text(encoding="utf-8")
            history_entries = [e.strip() for e in text.split("\n\n") if e.strip()]
            history_entries.reverse()  # newest first

        # Entity cards
        entities = []
        for card in _memory.entities.list_cards():
            entities.append({
                "name": card.name,
                "type": card.meta.get("type", ""),
                "keywords": card.keywords,
                "access_count": card.access_count,
                "body": card.body.strip(),
            })

        # Procedural rules
        rules = []
        for r in _memory.procedural.list_rules():
            rules.append({"trigger": r.get("trigger", ""), "lesson": r.get("lesson", ""), "action": r.get("action", "")})

        resp = _json({
            "core": core,
            "long_term": long_term,
            "today": today,
            "history": history_entries[:50],  # cap at 50 for UI
            "entities": entities,
            "rules": rules,
        })
        _maybe_refresh_cookie(request, resp)
        return resp

    async def update_memory_core(request: Request) -> Response:
        """9.2: Update core.md."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)
        content = body.get("content", "")
        if len(content) > 8000:
            return _json({"error": "Content too large (max 8000 characters)"}, 400)
        _memory.write_core(content)
        resp = _json({"ok": True})
        _maybe_refresh_cookie(request, resp)
        return resp

    async def update_entity(request: Request) -> Response:
        """9.2: Update entity card body."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        name = request.path_params["name"]
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)
        content = body.get("body", "")
        card = _memory.entities.get_card(name)
        if not card:
            return _json({"error": "Entity not found"}, 404)
        _memory.entities.update_card(name, content)
        resp = _json({"ok": True})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── 9.2b: SOUL.md (bootstrap file) API ──────────────────────────────

    _soul_path = agent_loop.workspace / "SOUL.md"

    async def get_soul(request: Request) -> Response:
        """Return SOUL.md content."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        content = ""
        if _soul_path.exists():
            content = _soul_path.read_text(encoding="utf-8")
        resp = _json({"content": content})
        _maybe_refresh_cookie(request, resp)
        return resp

    async def update_soul(request: Request) -> Response:
        """Update SOUL.md content."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)
        content = body.get("content", "")
        if len(content) > 16000:
            return _json({"error": "Content too large (max 16000 characters)"}, 400)
        _soul_path.write_text(content, encoding="utf-8")
        resp = _json({"ok": True})
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── 9.3: MCP status API ──────────────────────────────────────────────

    async def get_mcp_status(request: Request) -> Response:
        """9.3: Return MCP connection state and tool list."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        connected = getattr(agent_loop, "_mcp_connected", False)
        servers_cfg = getattr(agent_loop, "_mcp_servers", {})

        servers = []
        for name, cfg in servers_cfg.items():
            stype = "stdio" if "command" in cfg else "http"
            servers.append({"name": name, "type": stype})

        # Enumerate MCP tools from tool registry
        mcp_tools = []
        server_names = list(servers_cfg.keys())
        all_tool_names = sorted(agent_loop.tools.tool_names)
        for tool_name in all_tool_names:
            if not tool_name.startswith("mcp_"):
                continue
            # Match against known server names to split correctly
            matched_server = ""
            for sn in server_names:
                prefix = f"mcp_{sn}_"
                if tool_name.startswith(prefix):
                    matched_server = sn
                    break
            tool = tool_name[len(f"mcp_{matched_server}_"):] if matched_server else tool_name
            mcp_tools.append({"name": tool_name, "server": matched_server, "tool": tool})

        resp = _json({
            "connected": connected,
            "servers": servers,
            "tools": mcp_tools,
        })
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── 8.3: Yesterday Memo API ──────────────────────────────────────────

    async def get_yesterday_memo(request: Request) -> Response:
        """8.3: Extract yesterday's summary from HISTORY.md."""
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        entries = []
        if _memory.history_file.exists():
            text = _memory.history_file.read_text(encoding="utf-8")
            for entry in text.split("\n\n"):
                entry = entry.strip()
                if entry and yesterday in entry:
                    entries.append(entry)

        # Also include today's log
        today_log = _memory.today.read() or ""

        resp = _json({
            "yesterday": entries,
            "today": today_log,
            "date": yesterday,
        })
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── GET /api/info — instance status + version + session usage ──────

    async def get_info(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        data: dict = {"version": version}

        # Instance uptime
        if usage_tracker:
            data.update(usage_tracker.get_instance_summary())

        # Per-session usage if ?session=key
        session_key = request.query_params.get("session")
        if session_key and usage_tracker:
            if not session_key.startswith("webui:"):
                session_key = f"webui:{session_key}"
            session = session_manager._load(session_key)
            if session:
                data["session_usage"] = usage_tracker.get_session_summary(session.metadata)

        resp = _json(data)
        _maybe_refresh_cookie(request, resp)
        return resp

    # ── Assemble routes ──────────────────────────────────────────────────

    return [
        Route("/", index, methods=["GET"]),
        Route("/logo-icon.svg", logo_icon, methods=["GET"]),
        Route("/favicon.ico", logo_icon, methods=["GET"]),  # Use logo as favicon
        Route("/favicon.png", logo_64_png, methods=["GET"]), # High-compatibility favicon
        Route("/logo-64.png", logo_64_png, methods=["GET"]),
        Route("/vite.svg", vite_icon, methods=["GET"]),
        Route("/api/auth", auth_login, methods=["POST"]),
        Route("/api/auth", auth_logout, methods=["DELETE"]),
        Route("/api/auth/check", auth_check, methods=["GET"]),
        Route("/api/chat/upload", upload_file, methods=["POST"]),
        Route("/api/media", get_media, methods=["GET"]),
        Route("/api/chat/stream", chat_stream, methods=["POST"]),
        Route("/api/memory", get_memory, methods=["GET"]),
        Route("/api/memory/core", update_memory_core, methods=["PATCH"]),
        Route("/api/memory/entities/{name:path}", update_entity, methods=["PATCH"]),
        Route("/api/soul", get_soul, methods=["GET"]),
        Route("/api/soul", update_soul, methods=["PATCH"]),
        Route("/api/mcp/status", get_mcp_status, methods=["GET"]),
        Route("/api/memo/yesterday", get_yesterday_memo, methods=["GET"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/sessions/{key:path}/export", export_session, methods=["GET"]),
        Route("/api/sessions/{key:path}/messages", get_session_messages, methods=["GET"]),
        WebSocketRoute("/ws/session", ws_session),
        Route("/api/sessions/{key:path}", update_session, methods=["PATCH"]),
        Route("/api/sessions/{key:path}", delete_session, methods=["DELETE"]),
        Route("/api/models", list_models, methods=["GET"]),
        Route("/api/info", get_info, methods=["GET"]),
    ]
