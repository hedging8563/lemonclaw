"""WebUI route handlers — closure factory pattern matching server.py."""

from __future__ import annotations

import asyncio
import base64
import json
import importlib.resources
import tempfile
import time
import uuid
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
        logger.debug("importlib.resources load failed, trying filesystem fallback")

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

    # ── Async session title generation ────────────────────────────────────

    async def _generate_session_title(session_key: str, first_message: str) -> None:
        """Generate a short title for the session via Groq LLM, fallback to truncation."""
        session = session_manager.get_or_create(session_key)
        if session.metadata.get("title"):
            return  # Already has a title

        title = ""
        try:
            from lemonclaw.config.defaults import DEFAULT_CONSOLIDATION_MODEL
            resp = await asyncio.wait_for(
                agent_loop.provider.chat(
                    model=DEFAULT_CONSOLIDATION_MODEL,
                    messages=[
                        {"role": "system", "content": (
                            "Generate a short title (max 20 chars) for this conversation. "
                            "Reply with ONLY the title, no quotes, no punctuation at the end. "
                            "Use the same language as the user message."
                        )},
                        {"role": "user", "content": first_message[:500]},
                    ],
                    max_tokens=30,
                    temperature=0.3,
                ),
                timeout=5.0,
            )
            title = (resp.content or "").strip().strip('"\'').strip()[:30]
        except Exception as exc:
            logger.debug("Title generation failed ({}), using fallback", exc)

        # Fallback A: truncate first message
        if not title:
            title = first_message[:30].strip()
            if len(first_message) > 30:
                title += "…"

        session.metadata["title"] = title
        session_manager.save(session)

    # ── POST /api/chat/stream — SSE streaming ────────────────────────────

    # 7.1: Temp directory for uploaded files
    _upload_dir = Path(tempfile.mkdtemp(prefix="lemonclaw_uploads_"))

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
                final = await agent_loop.process_direct(
                    content=message,
                    session_key=session_key,
                    channel="webui",
                    chat_id="webui",
                    on_progress=on_progress,
                    on_chunk=on_chunk,
                    metadata={"timezone": user_timezone} if user_timezone else None,
                    media=media_files or None,
                )
                # Send final response
                event = {"type": "done", "data": final}
                await queue.put(f"data: {json.dumps(event, ensure_ascii=False)}\n\n")
                # Generate title for new sessions (fire-and-forget)
                s = session_manager.get_or_create(session_key)
                if not s.metadata.get("title"):
                    _t = asyncio.create_task(
                        _generate_session_title(session_key, message),
                        name=f"title-gen-{session_key}",
                    )
                    _t.add_done_callback(
                        lambda t: t.exception() and logger.warning("Title gen failed: {}", t.exception())
                    )
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

        resp = _json({
            "messages": messages,
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
        Route("/api/auth", auth_login, methods=["POST"]),
        Route("/api/auth", auth_logout, methods=["DELETE"]),
        Route("/api/auth/check", auth_check, methods=["GET"]),
        Route("/api/chat/upload", upload_file, methods=["POST"]),
        Route("/api/chat/stream", chat_stream, methods=["POST"]),
        Route("/api/memory", get_memory, methods=["GET"]),
        Route("/api/memory/core", update_memory_core, methods=["PATCH"]),
        Route("/api/memory/entities/{name:path}", update_entity, methods=["PATCH"]),
        Route("/api/mcp/status", get_mcp_status, methods=["GET"]),
        Route("/api/memo/yesterday", get_yesterday_memo, methods=["GET"]),
        Route("/api/sessions", list_sessions, methods=["GET"]),
        Route("/api/sessions/{key:path}/export", export_session, methods=["GET"]),
        Route("/api/sessions/{key:path}/messages", get_session_messages, methods=["GET"]),
        Route("/api/sessions/{key:path}", update_session, methods=["PATCH"]),
        Route("/api/sessions/{key:path}", delete_session, methods=["DELETE"]),
        Route("/api/models", list_models, methods=["GET"]),
        Route("/api/info", get_info, methods=["GET"]),
    ]
