from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.ledger.delivery import deliver_outbox_event
from lemonclaw.ledger.outbox import PermanentOutboxError


@pytest.mark.asyncio
async def test_deliver_outbox_event_publishes_outbound_message():
    sent: list[OutboundMessage] = []

    async def _publish(msg: OutboundMessage) -> None:
        sent.append(msg)

    await deliver_outbox_event(
        {
            "effect_type": "outbound_message",
            "target": "telegram:123",
            "payload": {"content": "hello"},
        },
        publish_outbound=_publish,
        notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
    )

    assert len(sent) == 1
    assert sent[0].channel == "telegram"
    assert sent[0].chat_id == "123"
    assert sent[0].content == "hello"


@pytest.mark.asyncio
async def test_deliver_outbox_event_webhook_dns_failure_is_retryable(monkeypatch: pytest.MonkeyPatch):
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for webhook effect")

    monkeypatch.setattr(
        "lemonclaw.ledger.delivery.deliver_webhook_json",
        AsyncMock(side_effect=RuntimeError("Webhook URL validation failed: DNS resolution failed")),
    )

    with pytest.raises(RuntimeError, match="DNS resolution failed"):
        await deliver_outbox_event(
            {
                "effect_type": "webhook_json",
                "target": "https://hooks.example.com/hook",
                "payload": {"title": "", "content": "hello"},
            },
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=["hooks.example.com"]),
        )


@pytest.mark.asyncio
async def test_deliver_outbox_event_unknown_effect_is_permanent():
    async def _publish(_msg: OutboundMessage) -> None:
        return None

    with pytest.raises(PermanentOutboxError):
        await deliver_outbox_event(
            {"effect_type": "unknown", "target": "x", "payload": {}},
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
        )
