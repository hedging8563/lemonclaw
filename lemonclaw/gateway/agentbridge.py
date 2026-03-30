"""AgentBridge runtime routes for coding-agent clients."""

from __future__ import annotations

import atexit
import asyncio
import base64
import hmac
import json
import mimetypes
import shutil
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.agentbridge import AgentBridgeChannel
from lemonclaw.channels.delivery_context import attach_delivery_context
from lemonclaw.channels.session_keys import build_agentbridge_session_key
from lemonclaw.gateway.runtime_context import GatewayRuntimeContext
from lemonclaw.gateway.webui.message_schema import serialize_ui_message
from lemonclaw.providers.catalog import resolve_model_id
from lemonclaw.providers.registry import provider_family_for_model

if TYPE_CHECKING:
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.channels.manager import ChannelManager
    from lemonclaw.session.manager import SessionManager
    from lemonclaw.telemetry.usage import UsageTracker


_NO_CACHE = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
_VALID_COMPONENT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
_SESSION_MEDIA_GRANT_TTL_S = 30 * 60
_SESSION_MEDIA_GRANT_MAX = 500


def _json(data: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code, headers=_NO_CACHE)


def _validate_component(name: str, value: Any, *, default: str | None = None) -> str:
    text = str(value or default or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    if len(text) > 64:
        raise ValueError(f"{name} must be at most 64 characters")
    if any(ch not in _VALID_COMPONENT for ch in text):
        raise ValueError(f"{name} contains invalid characters")
    return text


def _build_chat_identity(body: dict[str, Any]) -> dict[str, str]:
    client_id = _validate_component("client_id", body.get("client_id"))
    workspace_id = _validate_component("workspace_id", body.get("workspace_id"), default="default")
    thread_id = _validate_component("thread_id", body.get("thread_id"))
    session_key = build_agentbridge_session_key(
        client_id=client_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
    )
    chat_id = f"{client_id}:{workspace_id}:{thread_id}"
    return {
        "client_id": client_id,
        "workspace_id": workspace_id,
        "thread_id": thread_id,
        "chat_id": chat_id,
        "session_key": session_key,
    }


def _build_session_context(body: dict[str, Any]) -> dict[str, str]:
    timezone = str(body.get("timezone") or "").strip()[:64]
    run_mode = str(body.get("run_mode") or "interactive").strip()
    if run_mode not in {"interactive", "detached", "system"}:
        raise ValueError("run_mode must be one of: interactive, detached, system")
    return {
        "timezone": timezone,
        "run_mode": run_mode,
    }


def _rewrite_agentbridge_media_urls(message: dict[str, Any]) -> dict[str, Any]:
    payload = dict(message)
    raw_media = payload.get("media")
    if not isinstance(raw_media, list):
        return payload
    media = []
    for item in raw_media:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            media_item = dict(item)
            media_item["url"] = media_item["url"].replace("/api/media", "/api/agentbridge/media", 1)
            media.append(media_item)
        else:
            media.append(item)
    payload["media"] = media
    return payload


def _sse_line(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def get_agentbridge_routes(
    *,
    auth_token: str | None,
    runtime: GatewayRuntimeContext,
) -> list[Route]:
    """Build AgentBridge runtime routes."""

    agent_loop = runtime.agent_loop
    session_manager = runtime.session_manager
    channel_manager = runtime.channel_manager
    usage_tracker = runtime.usage_tracker

    if not (agent_loop and session_manager and channel_manager):
        return []

    _upload_dir = Path(tempfile.mkdtemp(prefix="lemonclaw_agentbridge_uploads_"))
    atexit.register(lambda path=_upload_dir: shutil.rmtree(path, ignore_errors=True))
    _attachments: dict[str, dict[str, Any]] = {}
    _session_media_grants: dict[str, dict[str, Any]] = {}

    def _require_auth(request: Request) -> tuple[bool, Response | None]:
        if not auth_token:
            return True, None
        header = request.headers.get("authorization", "")
        if hmac.compare_digest(header, f"Bearer {auth_token}"):
            return True, None
        return False, _json({"error": "Unauthorized"}, 401)

    def _agentbridge_enabled() -> bool:
        cfg = getattr(getattr(channel_manager.config, "channels", None), "agentbridge", None)
        return bool(getattr(cfg, "enabled", True))

    async def _ensure_channel() -> AgentBridgeChannel:
        existing = channel_manager.get_channel("agentbridge")
        if isinstance(existing, AgentBridgeChannel):
            return existing
        channel = AgentBridgeChannel(
            channel_manager.config.channels.agentbridge,
            channel_manager.bus,
            session_manager=session_manager,
        )
        await channel_manager.ensure_channel("agentbridge", channel)
        return channel

    def _cleanup_session_media_grants() -> None:
        now = time.time()
        expired = [
            key for key, value in _session_media_grants.items()
            if now - float(value.get("last_access", now)) > _SESSION_MEDIA_GRANT_TTL_S
        ]
        for key in expired:
            _session_media_grants.pop(key, None)
        if len(_session_media_grants) > _SESSION_MEDIA_GRANT_MAX:
            extra = len(_session_media_grants) - _SESSION_MEDIA_GRANT_MAX
            oldest = sorted(
                _session_media_grants.items(),
                key=lambda item: float(item[1].get("last_access", 0)),
            )[:extra]
            for key, _value in oldest:
                _session_media_grants.pop(key, None)

    def _touch_session_media_grants(session_key: str, paths: list[str] | None = None) -> None:
        now = time.time()
        entry = _session_media_grants.setdefault(session_key, {"paths": set(), "last_access": now})
        entry["last_access"] = now
        if paths:
            entry["paths"].update(paths)

    def _extract_message_grant_paths(message: dict[str, Any]) -> list[str]:
        media = message.get("media")
        if not isinstance(media, list):
            return []

        paths: list[str] = []
        for item in media:
            raw_path: str | None = None
            if isinstance(item, str):
                raw_path = item
            elif isinstance(item, dict) and item.get("source") == "media_field" and isinstance(item.get("path"), str):
                raw_path = item["path"]

            if not raw_path:
                continue

            try:
                resolved = Path(raw_path).expanduser().resolve(strict=False)
            except OSError:
                continue

            paths.append(str(resolved))
        return paths

    def _path_allowed_for_session(file_path: Path, session_key: str) -> bool:
        _cleanup_session_media_grants()
        entry = _session_media_grants.get(session_key)
        if entry and str(file_path) in entry.get("paths", set()):
            _touch_session_media_grants(session_key)
            return True
        session = session_manager.get(session_key)
        if not session:
            return False
        session_version = int(getattr(session, "version", 0) or 0)
        if entry and entry.get("scanned_version") == session_version:
            return False
        collected: list[str] = []
        for message in session.messages:
            collected.extend(_extract_message_grant_paths(message))
        if collected:
            _touch_session_media_grants(session_key, collected)
            _session_media_grants[session_key]["scanned_version"] = session_version
            return str(file_path) in _session_media_grants[session_key].get("paths", set())
        _session_media_grants[session_key] = {"paths": set(), "last_access": time.time(), "scanned_version": session_version}
        return False

    def _cleanup_uploads() -> None:
        if not _upload_dir.exists():
            return
        ttl = max(60, int(getattr(channel_manager.config.channels.agentbridge, "upload_ttl_seconds", 3600) or 3600))
        cutoff = time.time() - ttl
        expired_ids = [
            attachment_id
            for attachment_id, item in _attachments.items()
            if float(item.get("created_at", 0)) < cutoff
        ]
        for attachment_id in expired_ids:
            item = _attachments.pop(attachment_id, None)
            if not item:
                continue
            try:
                Path(item["path"]).unlink(missing_ok=True)
            except OSError:
                pass

    def _resolve_usage_summary(
        *,
        session_key: str,
        usage: UsageTracker | None,
        sessions: SessionManager,
    ) -> dict[str, Any] | None:
        if usage is None:
            return None
        session = sessions._load(session_key)
        if not session:
            return None
        return usage.get_session_summary(session.metadata)

    def _apply_model_override(body: dict[str, Any], *, session_key: str) -> str | None:
        requested = body.get("model")
        if not requested:
            return None
        model = resolve_model_id(str(requested)) or str(requested)
        session = session_manager.get_or_create(session_key)
        current_model = resolve_model_id(session.metadata.get("current_model") or getattr(agent_loop, "model", "")) or session.metadata.get("current_model") or getattr(agent_loop, "model", "")
        if session.messages and current_model and provider_family_for_model(current_model) != provider_family_for_model(model):
            raise RuntimeError("provider family conflict")
        session.metadata["current_model"] = model
        session_manager.save(session)
        return model

    def _materialize_messages(session_key: str, *, limit: int, before_idx: int | None) -> dict[str, Any]:
        session = session_manager._load(session_key)
        if not session:
            return {"messages": [], "has_more": False, "next_before": None}

        filtered: list[tuple[int, dict[str, Any]]] = []
        for idx, message in enumerate(session.messages):
            role = message.get("role", "")
            if role == "tool":
                continue
            if role in ("user", "assistant", "system", "tool_call"):
                filtered.append((idx, message))

        if before_idx is not None:
            filtered = [(idx, message) for idx, message in filtered if idx < before_idx]

        page = filtered[-limit:]
        has_more = len(filtered) > limit
        payload = []
        for _idx, message in page:
            item = serialize_ui_message(message, session_key=session_key)
            payload.append(_rewrite_agentbridge_media_urls(item))
            media_paths = _extract_message_grant_paths(message)
            if media_paths:
                _touch_session_media_grants(session_key, media_paths)

        return {
            "messages": payload,
            "has_more": has_more,
            "next_before": page[0][0] if page and has_more else None,
        }

    async def agentbridge_media(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]

        raw_path = request.query_params.get("path", "").strip()
        session_key = request.query_params.get("session_key", "").strip()
        if not raw_path or not session_key:
            return _json({"error": "path and session_key are required"}, 400)
        if not session_key.startswith("agentbridge:"):
            return _json({"error": "Invalid session"}, 400)

        try:
            file_path = Path(raw_path).expanduser().resolve(strict=True)
        except FileNotFoundError:
            return _json({"error": "file not found"}, 404)
        except OSError:
            return _json({"error": "invalid path"}, 400)

        if not _path_allowed_for_session(file_path, session_key):
            return _json({"error": "access denied"}, 403)

        media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        return FileResponse(file_path, media_type=media_type, filename=file_path.name, headers={"Cache-Control": "private, max-age=300"})

    async def agentbridge_uploads(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        if not _agentbridge_enabled():
            return _json({"error": "AgentBridge is disabled"}, 403)

        _cleanup_uploads()

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        data_url = str(body.get("data") or "")
        filename = str(body.get("filename") or "upload")
        if not data_url:
            return _json({"error": "No data"}, 400)

        if data_url.startswith("data:"):
            _header, b64 = data_url.split(",", 1) if "," in data_url else ("", data_url)
        else:
            b64 = data_url

        try:
            raw = base64.b64decode(b64)
        except Exception:
            return _json({"error": "Invalid base64"}, 400)

        max_upload_bytes = max(1, int(getattr(channel_manager.config.channels.agentbridge, "max_upload_bytes", 20 * 1024 * 1024) or 20 * 1024 * 1024))
        if len(raw) > max_upload_bytes:
            return _json({"error": f"File too large (max {max_upload_bytes} bytes)"}, 400)
        max_active_uploads = max(1, int(getattr(channel_manager.config.channels.agentbridge, "max_active_uploads", 128) or 128))
        if len(_attachments) >= max_active_uploads:
            return _json({"error": f"Too many active uploads (max {max_active_uploads})"}, 429)
        max_total_upload_bytes = max(
            max_upload_bytes,
            int(getattr(channel_manager.config.channels.agentbridge, "max_total_upload_bytes", 200 * 1024 * 1024) or 200 * 1024 * 1024),
        )
        active_upload_bytes = sum(int(item.get("size", 0) or 0) for item in _attachments.values())
        if active_upload_bytes + len(raw) > max_total_upload_bytes:
            return _json({"error": f"Active upload quota exceeded (max {max_total_upload_bytes} bytes)"}, 429)

        safe_name = "".join(ch for ch in filename if ch.isalnum() or ch in "._-")[:80] or "file"
        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        path = _upload_dir / unique_name
        path.write_bytes(raw)

        attachment_id = f"att_{uuid.uuid4().hex[:12]}"
        _attachments[attachment_id] = {
            "id": attachment_id,
            "path": str(path),
            "filename": safe_name,
            "size": len(raw),
            "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
            "created_at": time.time(),
        }

        return _json({"attachments": [{k: v for k, v in _attachments[attachment_id].items() if k != "path"}]})

    async def agentbridge_chat(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        if not _agentbridge_enabled():
            return _json({"error": "AgentBridge is disabled"}, 403)

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        message = str(body.get("message") or "").strip()
        if not message:
            return _json({"error": "message is required"}, 400)

        try:
            identity = _build_chat_identity(body)
            session_context = _build_session_context(body)
        except ValueError as exc:
            return _json({"error": str(exc)}, 400)

        attachments = []
        for item in body.get("attachments") or []:
            attachment = _attachments.get(str(item))
            if not attachment:
                return _json({"error": f"attachment not found: {item}"}, 404)
            attachments.append(attachment["path"])

        channel = await _ensure_channel()
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        try:
            requested_model = _apply_model_override(body, session_key=identity["session_key"])
        except RuntimeError:
            return _json({"error": "provider_family_conflict"}, 409)
        metadata = attach_delivery_context(
            channel="agentbridge",
            chat_id=identity["chat_id"],
            session_key=identity["session_key"],
            metadata={
                "_task_id": task_id,
                **({"model": requested_model} if requested_model else {}),
                "timezone": session_context["timezone"],
                "run_mode": session_context["run_mode"],
                "agentbridge": {
                    "request_id": request_id,
                    "client_id": identity["client_id"],
                    "workspace_id": identity["workspace_id"],
                    "thread_id": identity["thread_id"],
                    "session_context": session_context,
                    "metadata": body.get("metadata") or {},
                },
                "request_id": request_id,
            },
        )
        try:
            response = await agent_loop.process_direct(
                content=message,
                session_key=identity["session_key"],
                channel="agentbridge",
                chat_id=identity["chat_id"],
                media=attachments or None,
                metadata=metadata,
            )
        except Exception as exc:
            if "provider family" in str(exc).lower():
                return _json({"error": "provider_family_conflict"}, 409)
            logger.exception("AgentBridge chat failed")
            return _json({"error": str(exc)}, 500)

        for path in attachments:
            _touch_session_media_grants(identity["session_key"], [path])

        return _json(
            {
                "request_id": request_id,
                "task_id": task_id,
                "session_key": identity["session_key"],
                "final_message": response,
                "usage": _resolve_usage_summary(session_key=identity["session_key"], usage=usage_tracker, sessions=session_manager),
            }
        )

    async def agentbridge_chat_stream(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        if not _agentbridge_enabled():
            return _json({"error": "AgentBridge is disabled"}, 403)

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        message = str(body.get("message") or "").strip()
        if not message:
            return _json({"error": "message is required"}, 400)

        try:
            identity = _build_chat_identity(body)
            session_context = _build_session_context(body)
        except ValueError as exc:
            return _json({"error": str(exc)}, 400)

        attachments = []
        for item in body.get("attachments") or []:
            attachment = _attachments.get(str(item))
            if not attachment:
                return _json({"error": f"attachment not found: {item}"}, 404)
            attachments.append(attachment["path"])

        channel = await _ensure_channel()
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        try:
            requested_model = _apply_model_override(body, session_key=identity["session_key"])
        except RuntimeError:
            return _json({"error": "provider_family_conflict"}, 409)
        metadata = attach_delivery_context(
            channel="agentbridge",
            chat_id=identity["chat_id"],
            session_key=identity["session_key"],
            metadata={
                "_task_id": task_id,
                "request_id": request_id,
                **({"model": requested_model} if requested_model else {}),
                "timezone": session_context["timezone"],
                "run_mode": session_context["run_mode"],
                "agentbridge": {
                    "request_id": request_id,
                    "client_id": identity["client_id"],
                    "workspace_id": identity["workspace_id"],
                    "thread_id": identity["thread_id"],
                    "session_context": session_context,
                    "metadata": body.get("metadata") or {},
                },
            },
        )
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def on_progress(content: str, *, tool_hint: bool = False,
                              thinking: bool = False, tool_start: bool = False,
                              tool_result: bool = False) -> None:
            if thinking:
                event_type = "thinking"
                progress_kind = "thinking"
            elif tool_hint:
                event_type = "tool_hint"
                progress_kind = "tool_hint"
            elif tool_start:
                event_type = "tool_start"
                progress_kind = "tool_start"
            elif tool_result:
                event_type = "tool_result"
                progress_kind = "tool_result"
            else:
                event_type = "content"
                progress_kind = "content"
            await queue.put(
                _sse_line(
                    {
                        "type": event_type,
                        "data": content,
                        "session_key": identity["session_key"],
                        "progress_kind": progress_kind,
                    }
                )
            )

        async def on_chunk(content: str, *, first: bool = False) -> None:
            event: dict[str, Any] = {
                "type": "content",
                "data": content,
                "session_key": identity["session_key"],
                "progress_kind": "chunk",
            }
            if first:
                event["first"] = True
            await queue.put(_sse_line(event))

        async def outbound_sink(out_msg: OutboundMessage) -> None:
            if out_msg.media:
                _touch_session_media_grants(identity["session_key"], list(out_msg.media))
            event = await channel.emit(out_msg, session_key=identity["session_key"])
            if event["type"] == "outbound" and isinstance(event["data"], dict):
                event = dict(event)
                event["data"] = _rewrite_agentbridge_media_urls(event["data"])
            await queue.put(_sse_line(event))

        async def run_agent() -> None:
            try:
                await queue.put(
                    _sse_line(
                        {
                            "type": "meta",
                            "request_id": request_id,
                            "task_id": task_id,
                            "session_key": identity["session_key"],
                            "thread": {
                                "client_id": identity["client_id"],
                                "workspace_id": identity["workspace_id"],
                                "thread_id": identity["thread_id"],
                            },
                        }
                    )
                )
                final = await agent_loop.process_direct(
                    content=message,
                    session_key=identity["session_key"],
                    channel="agentbridge",
                    chat_id=identity["chat_id"],
                    media=attachments or None,
                    metadata=metadata,
                    on_progress=on_progress,
                    on_chunk=on_chunk,
                    outbound_sink=outbound_sink,
                )
                usage = _resolve_usage_summary(session_key=identity["session_key"], usage=usage_tracker, sessions=session_manager)
                await queue.put(
                    _sse_line(
                        {
                            "type": "done",
                            "session_key": identity["session_key"],
                            "data": {
                                "content": final,
                                "usage": usage,
                            },
                        }
                    )
                )
            except Exception as exc:
                status_code = 409 if "provider family" in str(exc).lower() else 500
                event = {
                    "type": "error",
                    "session_key": identity["session_key"],
                    "status_code": status_code,
                    "data": "provider_family_conflict" if status_code == 409 else str(exc),
                }
                await queue.put(_sse_line(event))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_agent())

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield _sse_line({"type": "ping"})
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

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store, private", "X-Accel-Buffering": "no"},
        )

    async def agentbridge_messages(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        if not _agentbridge_enabled():
            return _json({"error": "AgentBridge is disabled"}, 403)

        try:
            identity = _build_chat_identity(dict(request.query_params))
        except ValueError as exc:
            return _json({"error": str(exc)}, 400)

        try:
            limit = min(int(request.query_params.get("limit", "50")), 200)
        except (TypeError, ValueError):
            limit = 50
        try:
            before_idx = int(request.query_params.get("before")) if request.query_params.get("before") else None
        except (TypeError, ValueError):
            before_idx = None

        payload = _materialize_messages(identity["session_key"], limit=limit, before_idx=before_idx)
        return _json({"session_key": identity["session_key"], **payload})

    async def agentbridge_events_stream(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        if not _agentbridge_enabled():
            return _json({"error": "AgentBridge is disabled"}, 403)

        try:
            identity = _build_chat_identity(dict(request.query_params))
        except ValueError as exc:
            return _json({"error": str(exc)}, 400)

        channel = await _ensure_channel()
        queue, backlog = channel.subscribe(identity["session_key"])

        async def event_generator():
            try:
                for item in backlog:
                    event = deepcopy(item)
                    if event.get("type") == "outbound" and isinstance(event.get("data"), dict):
                        event["data"] = _rewrite_agentbridge_media_urls(event["data"])
                    yield _sse_line(event)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except asyncio.TimeoutError:
                        yield _sse_line({"type": "ping"})
                        continue
                    if item.get("type") == "closed":
                        break
                    event = deepcopy(item)
                    if event.get("type") == "outbound" and isinstance(event.get("data"), dict):
                        event["data"] = _rewrite_agentbridge_media_urls(event["data"])
                    yield _sse_line(event)
            finally:
                channel.unsubscribe(identity["session_key"], queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store, private", "X-Accel-Buffering": "no"},
        )

    async def agentbridge_stop(request: Request) -> Response:
        ok, err = _require_auth(request)
        if not ok:
            return err  # type: ignore[return-value]
        if not _agentbridge_enabled():
            return _json({"error": "AgentBridge is disabled"}, 403)

        try:
            body = await request.json()
        except Exception:
            return _json({"error": "Invalid JSON"}, 400)

        try:
            identity = _build_chat_identity(body)
        except ValueError as exc:
            return _json({"error": str(exc)}, 400)

        await _ensure_channel()
        metadata = attach_delivery_context(
            channel="agentbridge",
            chat_id=identity["chat_id"],
            session_key=identity["session_key"],
            metadata={"agentbridge": {"stop": True}},
        )
        result = await agent_loop.stop_session(
            identity["session_key"],
            channel="agentbridge",
            chat_id=identity["chat_id"],
            metadata=metadata,
        )
        return _json({"accepted": True, **result}, 202)

    return [
        Route("/api/agentbridge/media", agentbridge_media, methods=["GET"]),
        Route("/api/agentbridge/uploads", agentbridge_uploads, methods=["POST"]),
        Route("/api/agentbridge/chat", agentbridge_chat, methods=["POST"]),
        Route("/api/agentbridge/chat/stream", agentbridge_chat_stream, methods=["POST"]),
        Route("/api/agentbridge/messages", agentbridge_messages, methods=["GET"]),
        Route("/api/agentbridge/events/stream", agentbridge_events_stream, methods=["GET"]),
        Route("/api/agentbridge/stop", agentbridge_stop, methods=["POST"]),
    ]
