from __future__ import annotations

import pytest

from lemonclaw.agent.tools.notify import NotifyTool
from lemonclaw.bus.events import OutboundMessage


@pytest.mark.asyncio
async def test_notify_channel_uses_outbound_callback():
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = NotifyTool(send_callback=_send)
    result = await tool.execute(target_type="channel", content="hello", channel="cli", chat_id="direct")

    assert result["ok"] is True
    assert len(sent) == 1
    assert sent[0].content == "hello"


@pytest.mark.asyncio
async def test_notify_webhook_blocks_disallowed_domain():
    tool = NotifyTool(allow_webhook_domains=["hooks.example.com"])
    result = await tool.execute(target_type="webhook", content="hello", webhook_url="https://evil.example.com/hook")
    assert result["ok"] is False
    assert "not allowed" in result["summary"]


def test_notify_resolves_capability():
    tool = NotifyTool()
    assert tool.resolve_capability({"target_type": "channel"}) == "notify.channel.send"
    assert tool.resolve_capability({"target_type": "webhook"}) == "notify.webhook.send"


@pytest.mark.asyncio
async def test_notify_prefers_per_call_default_context_over_instance_context():
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = NotifyTool(send_callback=_send)
    tool.set_context("old", "stale")

    result = await tool.execute(
        target_type="channel",
        content="hello",
        _default_channel="fresh",
        _default_chat_id="target",
    )

    assert result["ok"] is True
    assert sent[0].channel == "fresh"
    assert sent[0].chat_id == "target"
