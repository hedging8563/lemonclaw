from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.wecom import WeComChannel
from lemonclaw.config.schema import WeComConfig


@pytest.mark.asyncio
async def test_wecom_blocks_media_download_before_allowlist_gate(tmp_path, monkeypatch) -> None:
    channel = WeComChannel(
        WeComConfig(
            enabled=True,
            corp_id="corp-id",
            secret="secret",
            agent_id=1000001,
            token="token",
            encoding_aes_key="abcdefghijklmnopqrstuvwxyzABCDEFG0123456789A",
            allow_from=["owner"],
        ),
        MessageBus(),
    )
    channel._handle_message = AsyncMock()
    channel._download_media = AsyncMock(return_value=str(tmp_path / "image.jpg"))
    monkeypatch.setattr("lemonclaw.channels.wecom.Path.home", lambda: tmp_path)

    await channel._process_message(
        {
            "MsgType": "image",
            "FromUserName": "blocked-user",
            "PicUrl": "https://wecom.example/image.jpg",
            "MsgId": "msg1",
        }
    )

    channel._download_media.assert_not_awaited()
    channel._handle_message.assert_not_awaited()
    media_dir = tmp_path / ".lemonclaw" / "media" / "wecom"
    assert not media_dir.exists()
