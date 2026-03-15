"""Outbox delivery helpers.

Best-effort durable outbox:
- delivery intents are durably recorded before send
- dispatch/retry is durable and auditable
- but this is not a transactional outbox tied atomically to every external
  side effect or process boundary
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from lemonclaw.agent.tools.notify import deliver_webhook_json
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.ledger.outbox import PermanentOutboxError

if TYPE_CHECKING:
    from lemonclaw.bus.queue import MessageBus
    from lemonclaw.config.schema import NotifyToolConfig


async def deliver_outbox_event(
    event: dict[str, Any],
    *,
    publish_outbound: Callable[[OutboundMessage], Awaitable[None]],
    notify_config: "NotifyToolConfig",
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

    raise PermanentOutboxError(f"unsupported outbox effect_type: {effect_type}")


def create_outbox_delivery_handler(
    *,
    bus: "MessageBus",
    notify_config: "NotifyToolConfig",
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def _deliver(event: dict[str, Any]) -> None:
        await deliver_outbox_event(
            event,
            publish_outbound=bus.publish_outbound,
            notify_config=notify_config,
        )

    return _deliver
