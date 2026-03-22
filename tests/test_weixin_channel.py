from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.weixin import WeixinChannel
from lemonclaw.config.schema import WeixinConfig


@pytest.mark.asyncio
async def test_weixin_bridge_event_passes_session_and_context_token() -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True, allow_from=["*"]), MessageBus())
    channel._handle_message = AsyncMock()

    await channel._handle_bridge_event(
        {
            "type": "message",
            "accountId": "bot-1",
            "senderId": "wx-user-9",
            "peerId": "wx-user-9",
            "chatId": "bot-1|wx-user-9",
            "content": "你好",
            "contextToken": "ctx-123",
            "messageId": 42,
            "timestamp": 1710000000,
            "metadata": {"itemTypes": ["text"], "hasMedia": False},
        }
    )

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "wx-user-9"
    assert kwargs["chat_id"] == "bot-1|wx-user-9"
    assert kwargs["session_key"] == "weixin:bot-1:wx-user-9"
    assert kwargs["metadata"]["account_id"] == "bot-1"
    assert kwargs["metadata"]["peer_id"] == "wx-user-9"
    assert kwargs["metadata"]["context_token"] == "ctx-123"


@pytest.mark.asyncio
async def test_weixin_send_uses_account_and_context_from_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, str | None] = {}

    def fake_send(config: WeixinConfig, *, account_id: str, to: str, text: str, context_token: str | None = None) -> dict[str, object]:
        sent["account_id"] = account_id
        sent["to"] = to
        sent["text"] = text
        sent["context_token"] = context_token
        return {"ok": True, "messageId": "m-1"}

    monkeypatch.setattr("lemonclaw.channels.weixin.send_weixin_text", fake_send)

    channel = WeixinChannel(WeixinConfig(enabled=True, allow_from=["*"]), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="weixin",
            chat_id="bot-1|wx-user-9",
            content="收到",
            metadata={
                "account_id": "bot-1",
                "peer_id": "wx-user-9",
                "context_token": "ctx-123",
            },
        )
    )

    assert sent == {
        "account_id": "bot-1",
        "to": "wx-user-9",
        "text": "收到",
        "context_token": "ctx-123",
    }
