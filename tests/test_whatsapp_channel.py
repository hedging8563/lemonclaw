from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.whatsapp import WhatsAppChannel
from lemonclaw.config.schema import WhatsAppConfig


@pytest.mark.asyncio
async def test_whatsapp_bridge_media_only_message_passes_media_paths() -> None:
    channel = WhatsAppChannel(
        WhatsAppConfig(enabled=True, allow_from=["*"]),
        MessageBus(),
    )
    channel._handle_message = AsyncMock()

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "id": "msg-1",
                "sender": "123456@s.whatsapp.net",
                "pn": "123456@s.whatsapp.net",
                "content": "",
                "timestamp": 1710000000,
                "isGroup": False,
                "media": ["/tmp/roman-history.docx"],
            }
        )
    )

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    assert kwargs["media"] == ["/tmp/roman-history.docx"]
    assert kwargs["content"] == ""


@pytest.mark.asyncio
async def test_whatsapp_bridge_duplicate_message_id_is_deduped() -> None:
    channel = WhatsAppChannel(
        WhatsAppConfig(enabled=True, allow_from=["*"]),
        MessageBus(),
    )
    channel._handle_message = AsyncMock()
    payload = {
        "type": "message",
        "id": "msg-dup",
        "sender": "123456@s.whatsapp.net",
        "pn": "123456@s.whatsapp.net",
        "content": "hello",
        "timestamp": 1710000000,
        "isGroup": False,
    }

    await channel._handle_bridge_message(json.dumps(payload))
    await channel._handle_bridge_message(json.dumps(payload))

    channel._handle_message.assert_awaited_once()
