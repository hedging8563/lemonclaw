"""Outbox delivery helpers.

Best-effort durable outbox:
- delivery intents are durably recorded before send
- dispatch/retry is durable and auditable
- but this is not a transactional outbox tied atomically to every external
  side effect or process boundary
"""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from lemonclaw.agent.tools.http_request import RETRYABLE_STATUS_CODES, _execute_http_request
from lemonclaw.agent.tools.notify import deliver_webhook_json
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.ledger.outbox import PermanentOutboxError

if TYPE_CHECKING:
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.config.schema import EmailConfig, HTTPRequestToolConfig, NotifyToolConfig


async def _send_email_smtp(
    *,
    to: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    from_address: str,
    use_tls: bool = True,
    use_ssl: bool = False,
) -> None:
    """Send a single email via SMTP using aiosmtplib."""
    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=smtp_host,
        port=smtp_port,
        username=smtp_username or None,
        password=smtp_password or None,
        start_tls=use_tls,
        use_tls=use_ssl,
    )


async def deliver_outbox_event(
    event: dict[str, Any],
    *,
    publish_outbound: Callable[[OutboundMessage], Awaitable[None]],
    notify_config: "NotifyToolConfig",
    http_config: "HTTPRequestToolConfig | None" = None,
    email_config: "EmailConfig | None" = None,
) -> None:
    """Deliver one outbox event.

    Raises:
        PermanentOutboxError: terminal misconfiguration or permanent 4xx failure.
        RuntimeError: retriable delivery failure.
    """
    effect_type = str(event.get("effect_type") or "")
    payload = dict(event.get("payload") or {})
    target = str(event.get("target") or "")

    if effect_type == "outbound_message":
        target_channel, target_chat_id = (target.split(":", 1) if ":" in target else ("", target))
        channel = str(payload.get("channel") or target_channel)
        chat_id = str(payload.get("chat_id") or target_chat_id)
        if not channel or not chat_id:
            raise PermanentOutboxError("outbox outbound_message requires channel/chat_id")

        await publish_outbound(OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=str(payload.get("content") or ""),
            reply_to=str(payload.get("reply_to") or "") or None,
            media=list(payload.get("media") or []),
            metadata=dict(payload.get("metadata") or {}),
        ))
        return

    if effect_type == "webhook_json":
        try:
            resp_status = await deliver_webhook_json(
                webhook_url=target,
                title=str(payload.get("title") or ""),
                content=str(payload.get("content") or ""),
                timeout=notify_config.timeout,
                allow_domains=list(notify_config.allow_webhook_domains or []),
            )
        except ValueError as exc:
            raise PermanentOutboxError(str(exc))
        except RuntimeError:
            raise
        if resp_status == 429 or resp_status >= 500:
            raise RuntimeError(f"webhook delivery -> {resp_status}")
        if resp_status >= 400:
            raise PermanentOutboxError(f"webhook delivery -> {resp_status}")
        return

    if effect_type == "http_json":
        method = str(payload.get("method") or "POST").upper()
        headers = dict(payload.get("headers") or {})
        query = dict(payload.get("query") or {})
        body = dict(payload.get("body") or {})
        auth_profile = str(payload.get("auth_profile") or "")
        expect_json = bool(payload.get("expect_json", True))
        request_timeout = int(payload.get("timeout") or (http_config.timeout if http_config else 30))
        allow_domains = list((http_config.allow_domains if http_config else []) or [])
        auth_profiles = dict((http_config.auth_profiles if http_config else {}) or {})

        result = await _execute_http_request(
            method=method,
            url=target,
            headers=headers,
            query=query,
            body=body,
            timeout=request_timeout,
            allow_domains=allow_domains,
            auth_profiles=auth_profiles,
            auth_profile=auth_profile,
            expect_json=expect_json,
        )

        if not result.ok and result.status_code is None:
            if result.dns_error:
                raise RuntimeError(f"URL validation failed: {result.error}")
            raise PermanentOutboxError(result.error or "Unknown error")

        if result.status_code is not None and result.status_code in RETRYABLE_STATUS_CODES:
            raise RuntimeError(f"http delivery -> {result.status_code}")
        if result.status_code is not None and result.status_code >= 400:
            raise PermanentOutboxError(f"http delivery -> {result.status_code}")
        return

    if effect_type == "email_send":
        if not email_config:
            raise PermanentOutboxError("email_send requires email configuration")
        if not email_config.smtp_host or not email_config.from_address:
            raise PermanentOutboxError("email_send requires smtp_host and from_address")
        to = target or str(payload.get("to") or "")
        subject = str(payload.get("subject") or "")
        body_text = str(payload.get("body") or "")
        if not to:
            raise PermanentOutboxError("email_send requires a recipient address")
        if email_config.smtp_use_tls and email_config.smtp_use_ssl:
            raise PermanentOutboxError("smtp_use_tls and smtp_use_ssl are mutually exclusive")
        try:
            await _send_email_smtp(
                to=to,
                subject=subject,
                body=body_text,
                smtp_host=email_config.smtp_host,
                smtp_port=email_config.smtp_port,
                smtp_username=email_config.smtp_username,
                smtp_password=email_config.smtp_password,
                from_address=email_config.from_address,
                use_tls=email_config.smtp_use_tls,
                use_ssl=email_config.smtp_use_ssl,
            )
        except ImportError as exc:
            raise PermanentOutboxError(f"email_send requires aiosmtplib: {exc}")
        except Exception as exc:
            if type(exc).__name__ == "SMTPAuthenticationError":
                raise PermanentOutboxError(f"email auth failed: {exc}")
            raise RuntimeError(f"email delivery failed: {err_str}")
        return

    raise PermanentOutboxError(f"unsupported outbox effect_type: {effect_type}")


def create_outbox_delivery_handler(
    *,
    bus: "MessageBus",
    notify_config: "NotifyToolConfig",
    http_config: "HTTPRequestToolConfig | None" = None,
    email_config: "EmailConfig | None" = None,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def _deliver(event: dict[str, Any]) -> None:
        await deliver_outbox_event(
            event,
            publish_outbound=bus.publish_outbound,
            notify_config=notify_config,
            http_config=http_config,
            email_config=email_config,
        )

    return _deliver
