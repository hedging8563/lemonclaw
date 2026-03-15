"""Notification tool for channel sends and webhooks."""

from __future__ import annotations

import fnmatch
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.web import USER_AGENT, _validate_url
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.ledger.runtime import TaskLedger


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


def prepare_webhook_delivery(
    webhook_url: str,
    allow_domains: list[str],
) -> tuple[str, dict[str, str], str]:
    parsed = urlparse(webhook_url)
    host = (parsed.hostname or "").lower()
    if not _host_allowed(host, allow_domains):
        raise ValueError(f"Webhook domain '{host}' is not allowed")
    validated, error, resolved_ip = _validate_url(webhook_url)
    if not validated:
        if error in {"DNS resolution failed", "No addresses returned by DNS"}:
            raise RuntimeError(f"Webhook URL validation failed: {error}")
        raise ValueError(f"Webhook URL validation failed: {error}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    request_url = webhook_url.replace(f"{parsed.scheme}://{parsed.netloc}", f"{parsed.scheme}://{resolved_ip}:{port}", 1)
    return request_url, {"User-Agent": USER_AGENT, "Host": parsed.netloc}, host


async def deliver_webhook_json(
    *,
    webhook_url: str,
    title: str,
    content: str,
    timeout: int,
    allow_domains: list[str],
) -> int:
    request_url, headers, _host = prepare_webhook_delivery(webhook_url, allow_domains)
    async with httpx.AsyncClient(timeout=float(timeout), follow_redirects=False) as client:
        resp = await client.post(
            request_url,
            json={"title": title, "content": content},
            headers=headers,
        )
    return resp.status_code


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
        _default_channel: str | None = None,
        _default_chat_id: str | None = None,
        _outbound_sink: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        _task_id: str | None = None,
        _task_ledger: TaskLedger | None = None,
        _step_id: str | None = None,
        _outbox_enabled: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if target_type == "channel":
            out_channel = channel or _default_channel or self._default_channel
            out_chat = chat_id or _default_chat_id or self._default_chat_id
            callback = _outbound_sink or self._send_callback
            if not out_channel or not out_chat:
                return {"ok": False, "summary": "Missing channel/chat target", "raw": {"channel": out_channel, "chat_id": out_chat}}
            if _outbox_enabled and _task_id and _task_ledger and _step_id:
                event = _task_ledger.enqueue_outbox(
                    task_id=_task_id,
                    step_id=_step_id,
                    effect_type="outbound_message",
                    target=f"{out_channel}:{out_chat}",
                    payload={
                        "channel": out_channel,
                        "chat_id": out_chat,
                        "content": content,
                        "metadata": {"title": title or ""},
                    },
                )
                return {
                    "ok": True,
                    "summary": f"Notification queued to {out_channel}:{out_chat}",
                    "step_status": "waiting_outbox",
                    "raw": {
                        "target_type": "channel",
                        "channel": out_channel,
                        "chat_id": out_chat,
                        "event_id": event["event_id"],
                        "queued": True,
                    },
                }
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
            try:
                prepare_webhook_delivery(webhook_url, self._allow_webhook_domains)
            except (ValueError, RuntimeError) as exc:
                return {"ok": False, "summary": str(exc), "raw": {"webhook_url": webhook_url}}
            if _outbox_enabled and _task_id and _task_ledger and _step_id:
                event = _task_ledger.enqueue_outbox(
                    task_id=_task_id,
                    step_id=_step_id,
                    effect_type="webhook_json",
                    target=webhook_url,
                    payload={"title": title or "", "content": content},
                )
                return {
                    "ok": True,
                    "summary": f"Webhook notification queued -> {host}",
                    "step_status": "waiting_outbox",
                    "raw": {
                        "target_type": "webhook",
                        "webhook_url": webhook_url,
                        "event_id": event["event_id"],
                        "queued": True,
                    },
                }
            resp_status = await deliver_webhook_json(
                webhook_url=webhook_url,
                title=title or "",
                content=content,
                timeout=self._timeout,
                allow_domains=self._allow_webhook_domains,
            )
            return {
                "ok": resp_status < 400,
                "summary": f"Webhook notification -> {resp_status}",
                "raw": {"target_type": "webhook", "webhook_url": webhook_url, "status_code": resp_status},
            }

        return {"ok": False, "summary": f"Unsupported target_type '{target_type}'", "raw": {"target_type": target_type}}
