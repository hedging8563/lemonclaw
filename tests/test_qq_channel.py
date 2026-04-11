from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.channels.qq import QQChannel
from lemonclaw.config.schema import QQConfig


class _DummyBus:
    async def publish_inbound(self, _msg):
        return None

    async def publish_outbound(self, _msg):
        return None


class _FakeResponse:
    def __init__(self, content: bytes = b"payload"):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeHttp:
    async def get(self, url: str):
        assert url == "https://files.example/doc.docx"
        return _FakeResponse()

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_qq_channel_downloads_attachment_only_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = QQChannel(QQConfig(enabled=True, app_id="app", secret="secret", allow_from=["*"]), _DummyBus())
    channel._http = _FakeHttp()

    monkeypatch.setattr("lemonclaw.channels.qq.Path.home", lambda: tmp_path)

    captured: dict[str, object] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture)

    attachment = SimpleNamespace(
        id="file123",
        filename="doc.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=128,
        url="https://files.example/doc.docx",
    )
    message = SimpleNamespace(
        id="msg1",
        author=SimpleNamespace(user_openid="user-openid"),
        content="",
        attachments=[attachment],
        message_reference=SimpleNamespace(message_id=None),
    )

    await channel._on_message(message)

    assert captured["sender_id"] == "user-openid"
    assert captured["chat_id"] == "user-openid"
    assert "[attachment:" in str(captured["content"])
    media = captured["media"]
    assert isinstance(media, list) and len(media) == 1
    assert media[0].endswith("file123_doc.docx")
    assert Path(media[0]).exists()


@pytest.mark.asyncio
async def test_qq_channel_keeps_text_and_attachment_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = QQChannel(QQConfig(enabled=True, app_id="app", secret="secret", allow_from=["*"]), _DummyBus())
    channel._http = _FakeHttp()

    monkeypatch.setattr("lemonclaw.channels.qq.Path.home", lambda: tmp_path)

    captured: dict[str, object] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(channel, "_handle_message", _capture)

    attachment = SimpleNamespace(
        id="file123",
        filename="doc.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=128,
        url="https://files.example/doc.docx",
    )
    message = SimpleNamespace(
        id="msg2",
        author=SimpleNamespace(user_openid="user-openid"),
        content="请帮我检查这份文档",
        attachments=[attachment],
        message_reference=SimpleNamespace(message_id=None),
    )

    await channel._on_message(message)

    assert "请帮我检查这份文档" in str(captured["content"])
    assert "[attachment:" in str(captured["content"])


@pytest.mark.asyncio
async def test_qq_channel_blocks_attachment_download_before_allowlist_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    channel = QQChannel(QQConfig(enabled=True, app_id="app", secret="secret", allow_from=["owner"]), _DummyBus())
    channel._http = SimpleNamespace(get=AsyncMock())

    monkeypatch.setattr("lemonclaw.channels.qq.Path.home", lambda: tmp_path)

    attachment = SimpleNamespace(
        id="file123",
        filename="doc.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=128,
        url="https://files.example/doc.docx",
    )
    message = SimpleNamespace(
        id="msg3",
        author=SimpleNamespace(user_openid="blocked-user"),
        content="",
        attachments=[attachment],
        message_reference=SimpleNamespace(message_id=None),
    )

    await channel._on_message(message)

    channel._http.get.assert_not_awaited()
    media_dir = tmp_path / ".lemonclaw" / "media" / "qq"
    assert not media_dir.exists()
