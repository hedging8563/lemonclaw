from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.channels.whatsapp import WhatsAppChannel
from lemonclaw.config.schema import WhatsAppConfig


_SUPPORTED_CONTENT_FIELDS = {
    "conversation",
    "extendedTextMessage",
    "imageMessage",
    "videoMessage",
    "documentMessage",
    "audioMessage",
}
_UNSUPPORTED_CONTENT_LABELS = {
    "stickerMessage": "sticker",
    "locationMessage": "location",
    "liveLocationMessage": "live location",
    "contactMessage": "contact",
    "contactsArrayMessage": "contacts",
    "pollCreationMessage": "poll",
    "pollUpdateMessage": "poll update",
    "reactionMessage": "reaction",
    "buttonsResponseMessage": "button response",
    "templateButtonReplyMessage": "template button reply",
    "listResponseMessage": "list response",
    "orderMessage": "order",
    "productMessage": "product",
    "protocolMessage": "protocol",
}


def _python_bridge_extract_content(message: dict[str, object]) -> str | None:
    payload = message.get("message")
    if not isinstance(payload, dict):
        return None

    if isinstance(payload.get("conversation"), str):
        return payload["conversation"]

    extended = payload.get("extendedTextMessage")
    if isinstance(extended, dict) and isinstance(extended.get("text"), str):
        return extended["text"]

    image = payload.get("imageMessage")
    if isinstance(image, dict):
        caption = image.get("caption")
        return f"[Image] {caption}" if isinstance(caption, str) and caption else "[Image]"

    video = payload.get("videoMessage")
    if isinstance(video, dict):
        caption = video.get("caption")
        return f"[Video] {caption}" if isinstance(caption, str) and caption else "[Video]"

    document = payload.get("documentMessage")
    if isinstance(document, dict):
        caption = document.get("caption")
        if isinstance(caption, str) and caption:
            return f"[Document] {caption}"
        filename = document.get("fileName") or document.get("title") or "document"
        return f"[Document] {filename}"

    if isinstance(payload.get("audioMessage"), dict):
        return "[Voice Message]"

    for key, label in _UNSUPPORTED_CONTENT_LABELS.items():
        if payload.get(key):
            return f"[Unsupported WhatsApp message type: {label}]"

    for key in payload:
        if key.endswith("Message") and key not in _SUPPORTED_CONTENT_FIELDS:
            normalized = key.removesuffix("Message")
            normalized = "".join(
                (f" {char.lower()}" if index and char.isupper() else char.lower())
                for index, char in enumerate(normalized)
            ).strip()
            return f"[Unsupported WhatsApp message type: {normalized}]"

    return None


def _bridge_extract_content(message: dict[str, object]) -> str | None:
    if shutil.which("pnpm") is None:
        # Python-only CI jobs do not install Node/pnpm. Keep the contract assertion
        # here so the Python suite does not silently depend on the bridge toolchain.
        return _python_bridge_extract_content(message)

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
    channel._resolve_bridge_media = AsyncMock(return_value=["/tmp/roman-history.docx"])

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
                "mediaToken": "media-1",
            }
        )
    )

    channel._resolve_bridge_media.assert_awaited_once_with("media-1")
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


@pytest.mark.asyncio
async def test_whatsapp_bridge_blocked_dm_does_not_resolve_media() -> None:
    channel = WhatsAppChannel(
        WhatsAppConfig(enabled=True, allow_from=["owner"]),
        MessageBus(),
    )
    channel._handle_message = AsyncMock()
    channel._resolve_bridge_media = AsyncMock(return_value=["/tmp/blocked.docx"])

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "id": "msg-blocked",
                "sender": "blocked@s.whatsapp.net",
                "pn": "blocked@s.whatsapp.net",
                "content": "",
                "timestamp": 1710000000,
                "isGroup": False,
                "mediaToken": "media-blocked",
            }
        )
    )

    channel._resolve_bridge_media.assert_not_awaited()
    channel._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_bridge_media_resolution_failure_surfaces_notice() -> None:
    channel = WhatsAppChannel(
        WhatsAppConfig(enabled=True, allow_from=["*"]),
        MessageBus(),
    )
    channel._handle_message = AsyncMock()
    channel._resolve_bridge_media = AsyncMock(return_value=None)
    channel._publish_feedback = AsyncMock()

    await channel._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "id": "msg-failed",
                "sender": "123456@s.whatsapp.net",
                "pn": "123456@s.whatsapp.net",
                "content": "",
                "timestamp": 1710000000,
                "isGroup": False,
                "mediaToken": "media-failed",
            }
        )
    )

    channel._resolve_bridge_media.assert_awaited_once_with("media-failed")
    channel._publish_feedback.assert_awaited_once()
    assert "bridge interruption" in channel._publish_feedback.await_args.args[1]
    channel._handle_message.assert_awaited_once()
    assert channel._handle_message.await_args.kwargs["media"] is None
