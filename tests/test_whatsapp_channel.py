from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.whatsapp import WhatsAppChannel
from lemonclaw.config.schema import WhatsAppConfig


def _bridge_extract_content(message: dict[str, object]) -> str | None:
    repo_root = Path(__file__).resolve().parents[2]
    script = f"""
import {{ WhatsAppClient }} from './lemonclaw/bridge/src/whatsapp.ts';

const client = new WhatsAppClient({{
  authDir: '/tmp/lemonclaw-whatsapp-test',
  onMessage() {{}},
  onQR() {{}},
  onStatus() {{}},
}});
const result = (client as any).extractMessageContent({json.dumps(message)});
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["pnpm", "exec", "tsx", "--eval", script],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip())


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
async def test_whatsapp_send_uses_visible_marker_when_media_cannot_be_sent() -> None:
    class FakeWS:
        def __init__(self) -> None:
            self.sent: str | None = None

        async def send(self, payload: str) -> None:
            self.sent = payload

    channel = WhatsAppChannel(
        WhatsAppConfig(enabled=True, allow_from=["*"]),
        MessageBus(),
    )
    channel._ws = FakeWS()
    channel._connected = True

    await channel.send(
        OutboundMessage(
            channel="whatsapp",
            chat_id="123456@s.whatsapp.net",
            content="",
            media=["/tmp/report.pdf"],
        )
    )

    payload = json.loads(channel._ws.sent or "{}")
    assert payload["text"] == "[Media omitted: 1 file(s)]"


def test_whatsapp_bridge_unsupported_message_types_emit_explicit_marker() -> None:
    content = _bridge_extract_content(
        {
            "message": {
                "stickerMessage": {
                    "fileSha256": "abc123",
                }
            }
        }
    )

    assert content == "[Unsupported WhatsApp message type: sticker]"


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
