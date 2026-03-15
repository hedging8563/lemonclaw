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


@pytest.mark.asyncio
async def test_deliver_outbox_event_http_json_dns_failure_is_retryable(monkeypatch: pytest.MonkeyPatch):
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for http_json effect")

    from lemonclaw.agent.tools.http_request import HTTPRequestResult

    async def _fake_execute(**kwargs):
        return HTTPRequestResult(
            ok=False, status_code=None, final_url=kwargs["url"], method=kwargs["method"],
            headers={}, body=None, error="URL validation failed: DNS resolution failed", dns_error=True,
        )

    monkeypatch.setattr("lemonclaw.ledger.delivery._execute_http_request", _fake_execute)

    with pytest.raises(RuntimeError, match="DNS resolution failed"):
        await deliver_outbox_event(
            {
                "effect_type": "http_json",
                "target": "https://example.com/data",
                "payload": {"method": "POST", "body": {"hello": "world"}},
            },
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
            http_config=SimpleNamespace(timeout=30, allow_domains=["example.com"], auth_profiles={}),
        )


@pytest.mark.asyncio
async def test_deliver_outbox_event_http_json_408_is_retryable(monkeypatch: pytest.MonkeyPatch):
    """408 Request Timeout should be retryable, not permanent."""
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for http_json effect")

    from lemonclaw.agent.tools.http_request import HTTPRequestResult

    async def _fake_execute(**kwargs):
        return HTTPRequestResult(
            ok=False, status_code=408, final_url=kwargs["url"], method=kwargs["method"],
            headers={}, body=None,
        )

    monkeypatch.setattr("lemonclaw.ledger.delivery._execute_http_request", _fake_execute)

    with pytest.raises(RuntimeError, match="http delivery -> 408"):
        await deliver_outbox_event(
            {
                "effect_type": "http_json",
                "target": "https://example.com/data",
                "payload": {"method": "POST", "body": {"hello": "world"}},
            },
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
            http_config=SimpleNamespace(timeout=30, allow_domains=["example.com"], auth_profiles={}),
        )


@pytest.mark.asyncio
async def test_deliver_outbox_event_http_json_permanent_4xx(monkeypatch: pytest.MonkeyPatch):
    """Non-retryable 4xx (e.g. 403) should raise PermanentOutboxError."""
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for http_json effect")

    from lemonclaw.agent.tools.http_request import HTTPRequestResult

    async def _fake_execute(**kwargs):
        return HTTPRequestResult(
            ok=False, status_code=403, final_url=kwargs["url"], method=kwargs["method"],
            headers={}, body=None,
        )

    monkeypatch.setattr("lemonclaw.ledger.delivery._execute_http_request", _fake_execute)

    with pytest.raises(PermanentOutboxError, match="http delivery -> 403"):
        await deliver_outbox_event(
            {
                "effect_type": "http_json",
                "target": "https://example.com/data",
                "payload": {"method": "POST", "body": {"hello": "world"}},
            },
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
            http_config=SimpleNamespace(timeout=30, allow_domains=["example.com"], auth_profiles={}),
        )


@pytest.mark.asyncio
async def test_deliver_outbox_event_email_send_missing_config_is_permanent():
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for email_send effect")

    with pytest.raises(PermanentOutboxError, match="email_send requires email configuration"):
        await deliver_outbox_event(
            {
                "effect_type": "email_send",
                "target": "user@example.com",
                "payload": {"subject": "Test", "body": "Hello"},
            },
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
            email_config=None,
        )


@pytest.mark.asyncio
async def test_deliver_outbox_event_email_send_success(monkeypatch: pytest.MonkeyPatch):
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for email_send effect")

    sent: list[dict] = []

    async def _fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("lemonclaw.ledger.delivery._send_email_smtp", _fake_send)

    email_cfg = SimpleNamespace(
        smtp_host="smtp.example.com", smtp_port=587,
        smtp_username="user", smtp_password="pass",
        from_address="bot@example.com",
        smtp_use_tls=True, smtp_use_ssl=False,
    )
    await deliver_outbox_event(
        {
            "effect_type": "email_send",
            "target": "recipient@example.com",
            "payload": {"subject": "Test Subject", "body": "Hello World"},
        },
        publish_outbound=_publish,
        notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
        email_config=email_cfg,
    )

    assert len(sent) == 1
    assert sent[0]["to"] == "recipient@example.com"
    assert sent[0]["subject"] == "Test Subject"


@pytest.mark.asyncio
async def test_deliver_outbox_event_email_send_transient_error_is_retryable(monkeypatch: pytest.MonkeyPatch):
    async def _publish(_msg: OutboundMessage) -> None:
        raise AssertionError("should not publish outbound for email_send effect")

    async def _fake_send(**kwargs):
        raise RuntimeError("smtp timeout")

    monkeypatch.setattr("lemonclaw.ledger.delivery._send_email_smtp", _fake_send)

    email_cfg = SimpleNamespace(
        smtp_host="smtp.example.com", smtp_port=587,
        smtp_username="user", smtp_password="pass",
        from_address="bot@example.com",
        smtp_use_tls=True, smtp_use_ssl=False,
    )

    with pytest.raises(RuntimeError, match="email delivery failed: smtp timeout"):
        await deliver_outbox_event(
            {
                "effect_type": "email_send",
                "target": "recipient@example.com",
                "payload": {"subject": "Test Subject", "body": "Hello World"},
            },
            publish_outbound=_publish,
            notify_config=SimpleNamespace(timeout=15, allow_webhook_domains=[]),
            email_config=email_cfg,
        )
