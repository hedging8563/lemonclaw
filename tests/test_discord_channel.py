from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.discord import DiscordChannel
from lemonclaw.config.schema import DiscordConfig


@pytest.mark.asyncio
async def test_discord_blocks_attachment_download_before_allowlist_gate(tmp_path, monkeypatch) -> None:
    channel = DiscordChannel(DiscordConfig(enabled=True, token="token", allow_from=["owner"]), MessageBus())
    channel._http = SimpleNamespace(get=AsyncMock())
    channel._handle_message = AsyncMock()
    channel._start_typing = AsyncMock()
    monkeypatch.setattr("lemonclaw.channels.discord.Path.home", lambda: tmp_path)

    await channel._handle_message_create(
        {
            "id": "msg1",
            "channel_id": "dm-1",
            "content": "",
            "author": {"id": "blocked-user", "bot": False},
            "attachments": [
                {
                    "id": "file123",
                    "filename": "notes.txt",
                    "url": "https://cdn.discordapp.com/files/notes.txt",
                    "size": 128,
                }
            ],
        }
    )

    channel._http.get.assert_not_awaited()
    channel._handle_message.assert_not_awaited()
    channel._start_typing.assert_not_awaited()
    media_dir = tmp_path / ".lemonclaw" / "media"
    assert not media_dir.exists()
