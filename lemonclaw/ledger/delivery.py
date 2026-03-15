"""Outbox delivery helpers.

Best-effort durable outbox:
- delivery intents are durably recorded before send
- dispatch/retry is durable and auditable
- but this is not a transactional outbox tied atomically to every external
  side effect or process boundary
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

import httpx
from urllib.parse import urlparse

from lemonclaw.agent.tools.http_request import _domain_allowed
from lemonclaw.agent.tools.notify import deliver_webhook_json
from lemonclaw.agent.tools.web import MAX_REDIRECTS, USER_AGENT, _validate_url
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.ledger.outbox import PermanentOutboxError

if TYPE_CHECKING:
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.config.schema import HTTPRequestToolConfig, NotifyToolConfig


async def deliver_outbox_event(
    event: dict[str, Any],
    *,
    publish_outbound: Callable[[OutboundMessage], Awaitable[None]],
    notify_config: "NotifyToolConfig",
    http_config: "HTTPRequestToolConfig | None" = None,
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

        parsed = urlparse(target)
        host = (parsed.hostname or "").lower()
        if not _domain_allowed(host, allow_domains):
            raise PermanentOutboxError(f"Domain '{host}' is not in allow_domains")
        if auth_profile:
            profile_headers = auth_profiles.get(auth_profile)
            if not profile_headers:
                raise PermanentOutboxError(f"Unknown auth profile '{auth_profile}'")
            for key, value in profile_headers.items():
                headers.setdefault(key, value)

        validated, error, resolved_ip = _validate_url(target)
        if not validated:
            if error in {"DNS resolution failed", "No addresses returned by DNS"}:
                raise RuntimeError(f"URL validation failed: {error}")
            raise PermanentOutboxError(f"URL validation failed: {error}")

        response = None
        current_url = target
        current_ip = resolved_ip
        current_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        transport = httpx.AsyncHTTPTransport()
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                transport=transport,
                timeout=float(request_timeout),
                verify=True,
            ) as client:
                for _ in range(MAX_REDIRECTS):
                    current_parsed = urlparse(current_url)
                    request_url = current_url.replace(
                        f"{current_parsed.scheme}://{current_parsed.netloc}",
                        f"{current_parsed.scheme}://{current_ip}:{current_port}",
                        1,
                    )
                    req_headers = {"User-Agent": USER_AGENT, "Host": current_parsed.netloc, **headers}
                    response = await client.request(
                        method,
                        request_url,
                        headers=req_headers,
                        params=query if method in {"GET", "HEAD", "DELETE"} else None,
                        json=body if method not in {"GET", "HEAD"} and body else None,
                    )
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location", "")
                        if not location:
                            break
                        if location.startswith("/"):
                            location = f"{current_parsed.scheme}://{current_parsed.netloc}{location}"
                        redir_ok, redir_err, redir_ip = _validate_url(location)
                        if not redir_ok:
                            if redir_err in {"DNS resolution failed", "No addresses returned by DNS"}:
                                raise RuntimeError(f"Redirect validation failed: {redir_err}")
                            raise PermanentOutboxError(f"Redirect blocked: {redir_err}")
                        redir_parsed = urlparse(location)
                        redir_host = (redir_parsed.hostname or "").lower()
                        if not _domain_allowed(redir_host, allow_domains):
                            raise PermanentOutboxError(f"Redirect domain '{redir_host}' is not in allow_domains")
                        current_url = location
                        current_ip = redir_ip
                        current_port = redir_parsed.port or (443 if redir_parsed.scheme == "https" else 80)
                        continue
                    break
        except PermanentOutboxError:
            raise
        except Exception as exc:
            raise RuntimeError(f"HTTP request failed: {exc}")

        if response is None:
            raise RuntimeError("No response received")
        if response.status_code == 429 or response.status_code >= 500:
            raise RuntimeError(f"http delivery -> {response.status_code}")
        if response.status_code >= 400:
            raise PermanentOutboxError(f"http delivery -> {response.status_code}")
        return

    raise PermanentOutboxError(f"unsupported outbox effect_type: {effect_type}")


def create_outbox_delivery_handler(
    *,
    bus: "MessageBus",
    notify_config: "NotifyToolConfig",
    http_config: "HTTPRequestToolConfig | None" = None,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def _deliver(event: dict[str, Any]) -> None:
        await deliver_outbox_event(
            event,
            publish_outbound=bus.publish_outbound,
            notify_config=notify_config,
            http_config=http_config,
        )

    return _deliver
