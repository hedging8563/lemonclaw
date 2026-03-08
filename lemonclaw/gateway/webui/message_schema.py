"""Normalize backend session / SSE messages into the WebUI UIMessage shape."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_MEDIA_TOKEN_RE = re.compile(r"\[(transcription|image|audio|voice|video|pdf|file|document):\s*([^\]]+)\]", re.IGNORECASE)
_RUNTIME_PREFIX = "[Runtime Context"


def _format_tool_call_detail(tool: dict[str, Any]) -> str:
    detail = tool.get("detail")
    if isinstance(detail, str) and detail:
        return detail
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    name = fn.get("name") or tool.get("name") or "tool_call"
    args_raw = fn.get("arguments")
    try:
        args = args_raw if isinstance(args_raw, dict) else re.sub(r"\s+", " ", str(args_raw or "")).strip()
        if isinstance(args, str):
            import json as _json
            args = _json.loads(args) if args else {}
        first_val = next(iter(args.values()), "") if isinstance(args, dict) else ""
        if isinstance(first_val, str):
            preview = first_val[:40] + "..." if len(first_val) > 40 else first_val
            return f'{name}("{preview}")' if preview else name
        if first_val not in (None, ""):
            return f"{name}({first_val})"
    except Exception:
        pass
    return name


def extract_message_media_paths(raw: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    media = raw.get("media")
    if isinstance(media, list):
        for item in media:
            if isinstance(item, str):
                paths.append(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("path"):
                paths.append(item["path"])
    content = raw.get("content")
    if isinstance(content, str):
        for match in _MEDIA_TOKEN_RE.finditer(content):
            kind = match.group(1).lower()
            if kind == 'transcription':
                continue
            payload = match.group(2).strip()
            file_match = re.match(r"^(.*?)(?:\s*\(([^()]+)\))?$", payload)
            media_path = (file_match.group(1) if file_match else payload).strip()
            if media_path:
                paths.append(media_path)
    # preserve order while deduping
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def media_url(path: str, session_key: str | None = None) -> str:
    if path.startswith(("http://", "https://")):
        return path
    from urllib.parse import quote
    encoded = quote(path, safe='')
    if session_key:
        return f"/api/media?path={encoded}&session_key={quote(session_key, safe='')}"
    return f"/api/media?path={encoded}"


def _extract_runtime_context(content: str) -> tuple[str | None, str]:
    if not content.startswith(_RUNTIME_PREFIX):
        return None, content
    marker = "\n\n"
    idx = content.find(marker)
    if idx == -1:
        return content, ""
    return content[:idx].strip(), content[idx + len(marker):].strip()


def _infer_media_kind(path: str, hinted: str | None = None) -> str:
    lower = path.lower()
    if hinted in {"image", "audio", "voice", "video", "pdf", "file", "document"}:
        return hinted
    if re.search(r"\.(png|jpe?g|gif|webp|bmp|svg)$", lower):
        return "image"
    if re.search(r"\.(mp3|wav|m4a|aac|ogg|opus|flac)$", lower):
        return "voice" if lower.endswith(".ogg") else "audio"
    if re.search(r"\.(mp4|webm|mov|mkv|avi)$", lower):
        return "video"
    if lower.endswith('.pdf'):
        return 'pdf'
    return 'file'


def _basename(path: str) -> str:
    return Path(path).name or path


def _parse_content_blocks(content: str, raw_media: list[str] | None = None, *, session_key: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runtime, body = _extract_runtime_context(content or "")
    media: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    media_ids: dict[tuple[str, str], str] = {}
    media_counter = 0

    def register_media(path: str, hinted: str | None = None, label: str | None = None) -> str:
        nonlocal media_counter
        key = (hinted or "", path)
        if key in media_ids:
            return media_ids[key]
        media_counter += 1
        media_id = f"m{media_counter}"
        media_ids[key] = media_id
        media.append({
            "id": media_id,
            "kind": _infer_media_kind(path, hinted),
            "path": path,
            "url": media_url(path, session_key),
            "filename": label or _basename(path),
        })
        return media_id

    if runtime:
        blocks.append({"type": "runtime_context", "text": runtime, "collapsed": True})

    last_index = 0
    for match in _MEDIA_TOKEN_RE.finditer(body):
        text_part = body[last_index:match.start()].strip()
        if text_part:
            blocks.append({"type": "markdown", "text": text_part})
        kind = match.group(1).lower()
        payload = match.group(2).strip()
        if kind == 'transcription':
            blocks.append({"type": "transcription", "text": payload})
        else:
            file_match = re.match(r"^(.*?)(?:\s*\(([^()]+)\))?$", payload)
            media_path = (file_match.group(1) if file_match else payload).strip()
            label = file_match.group(2).strip() if file_match and file_match.group(2) else None
            media_id = register_media(media_path, kind, label)
            blocks.append({"type": "media", "mediaId": media_id})
        last_index = match.end()

    tail = body[last_index:].strip()
    if tail:
        blocks.append({"type": "markdown", "text": tail})

    for path in raw_media or []:
        media_id = register_media(path)
        blocks.append({"type": "media", "mediaId": media_id})

    return media, blocks


def serialize_ui_message(raw: dict[str, Any], *, session_key: str | None = None) -> dict[str, Any]:
    # Pass through if already normalized
    if isinstance(raw.get("blocks"), list) and isinstance(raw.get("media"), list):
        msg = dict(raw)
        msg["media"] = [
            {**m, **({"url": media_url(m.get("path", ""), session_key)} if m.get("path") else {})} if isinstance(m, dict) else m
            for m in raw.get("media", [])
        ]
        return msg

    role = raw.get("role", "assistant")
    raw_content = raw.get("content", "")
    if isinstance(raw_content, list):
        # Multimodal content array (e.g. from Anthropic) — extract text parts
        content = " ".join(p.get("text", "") for p in raw_content if isinstance(p, dict) and p.get("type") == "text")
    elif isinstance(raw_content, str):
        content = raw_content
    else:
        content = ""
    raw_media = [m for m in raw.get("media", []) if isinstance(m, str)] if isinstance(raw.get("media"), list) else []
    media, blocks = _parse_content_blocks(content, raw_media, session_key=session_key)

    message: dict[str, Any] = {
        "id": raw.get("id"),
        "role": role,
        "content": content,
        "media": media,
        "blocks": [],
        "timestamp": raw.get("timestamp"),
    }

    thinking = raw.get("thinking")
    if isinstance(thinking, str) and thinking:
        message["blocks"].append({"type": "thinking", "text": thinking})

    tool_calls = raw.get("tool_calls")
    meta = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
    notice_text = meta.get("_ui_notice_text")
    notice_kind = meta.get("_ui_notice_kind", "system")
    notice_level = meta.get("_ui_notice_level", "info")
    if isinstance(notice_text, str) and notice_text:
        message["blocks"].append({"type": "system_notice", "text": notice_text, "kind": notice_kind, "level": notice_level})

    if isinstance(tool_calls, list):
        for tool in tool_calls:
            if isinstance(tool, dict):
                message["blocks"].append({
                    "type": "tool",
                    "state": tool.get("state", "done"),
                    "detail": _format_tool_call_detail(tool),
                    "result": tool.get("result"),
                })

    if role == 'tool_call' and content:
        message["blocks"].append({"type": "tool", "state": "done", "detail": content})

    message["blocks"].extend(blocks)

    if raw.get("error"):
        message["error"] = str(raw["error"])
        message["blocks"].append({"type": "error", "text": str(raw["error"])})

    return message
