"""Notification tool for channel sends and webhooks."""

from __future__ import annotations

import fnmatch
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.web import USER_AGENT, _validate_url
from lemonclaw.bus.events import OutboundMessage


def _host_allowed(host: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    host = host.lower()
    for pattern in patterns:
        p = pattern.strip().lower()
        if not p:
            continue
        if fnmatch.fnmatch(host, p):
            return True
        if p.startswith("*.") and (host == p[2:] or host.endswith("." + p[2:])):
            return True
        if host == p:
            return True
    return False


class NotifyTool(Tool):
    """Send notifications to channels or webhooks."""

    def __init__(
        self,
        *,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        timeout: int = 15,
        allow_webhook_domains: list[str] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self._send_callback = send_callback
        self._timeout = timeout
        self._allow_webhook_domains = allow_webhook_domains or []
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id

    def set_context(self, channel: str, chat_id: str) -> None:
        self._default_channel = channel
        self._default_chat_id = chat_id

    @property
    def name(self) -> str:
        return "notify"

    @property
    def description(self) -> str:
        return (
            "Send a notification to either a chat channel or a webhook. "
            "Use this when a task result should be delivered outside the current reply."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_type": {
                    "type": "string",
                    "enum": ["channel", "webhook"],
                    "description": "Notification target type.",
                },
                "content": {
                    "type": "string",
                    "description": "Notification body content.",
                    "minLength": 1,
                },
                "channel": {
                    "type": "string",
                    "description": "Target channel when target_type=channel.",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Target chat id when target_type=channel.",
                },
                "webhook_url": {
                    "type": "string",
                    "description": "Webhook URL when target_type=webhook.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title for structured notifications.",
                },
            },
            "required": ["target_type", "content"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        target_type = str(params.get("target_type", "channel"))
        if target_type == "webhook":
            return "notify.webhook.send"
        return "notify.channel.send"

    async def execute(
        self,
        target_type: str,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        webhook_url: str | None = None,
        title: str | None = None,
        _outbound_sink: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if target_type == "channel":
            out_channel = channel or self._default_channel
            out_chat = chat_id or self._default_chat_id
            callback = _outbound_sink or self._send_callback
            if not out_channel or not out_chat:
                return {"ok": False, "summary": "Missing channel/chat target", "raw": {"channel": out_channel, "chat_id": out_chat}}
            if not callback:
                return {"ok": False, "summary": "Notification channel callback not configured", "raw": {"channel": out_channel}}
            msg = OutboundMessage(channel=out_channel, chat_id=out_chat, content=content, metadata={"title": title or ""})
            await callback(msg)
            return {"ok": True, "summary": f"Notification sent to {out_channel}:{out_chat}", "raw": {"target_type": "channel", "channel": out_channel, "chat_id": out_chat}}

        if target_type == "webhook":
            if not webhook_url:
                return {"ok": False, "summary": "Missing webhook_url", "raw": {}}
            parsed = urlparse(webhook_url)
            host = (parsed.hostname or "").lower()
            if not _host_allowed(host, self._allow_webhook_domains):
                return {"ok": False, "summary": f"Webhook domain '{host}' is not allowed", "raw": {"webhook_url": webhook_url}}
            validated, error, resolved_ip = _validate_url(webhook_url)
            if not validated:
                return {"ok": False, "summary": f"Webhook URL validation failed: {error}", "raw": {"webhook_url": webhook_url}}
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            request_url = webhook_url.replace(f"{parsed.scheme}://{parsed.netloc}", f"{parsed.scheme}://{resolved_ip}:{port}", 1)
            payload = {"title": title or "", "content": content}
            async with httpx.AsyncClient(timeout=float(self._timeout), follow_redirects=False) as client:
                resp = await client.post(
                    request_url,
                    json=payload,
                    headers={"User-Agent": USER_AGENT, "Host": parsed.netloc},
                )
            return {
                "ok": resp.status_code < 400,
                "summary": f"Webhook notification -> {resp.status_code}",
                "raw": {"target_type": "webhook", "webhook_url": webhook_url, "status_code": resp.status_code},
            }

        return {"ok": False, "summary": f"Unsupported target_type '{target_type}'", "raw": {"target_type": target_type}}
