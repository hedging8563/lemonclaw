"""Tests for group_policy gate across IM channels.

Covers the four policies: open, mention, allowlist, disabled.
Each channel's group gate is tested in isolation by mocking _handle_message.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.config.schema import (
    DiscordConfig,
    FeishuConfig,
    QQConfig,
    TelegramConfig,
    WhatsAppConfig,
)


# ─── Telegram ────────────────────────────────────────────────────────────


def _tg_channel(*, group_policy="mention", group_allow_from=None, group_require_mention=True):
    from lemonclaw.channels.telegram import TelegramChannel

    config = TelegramConfig(
        enabled=True,
        token="test-token",
        group_policy=group_policy,
        group_allow_from=group_allow_from or [],
        group_require_mention=group_require_mention,
    )
    ch = TelegramChannel(config, MessageBus())
    # Stub bot with username for mention detection
    ch._app = SimpleNamespace(bot=SimpleNamespace(username="testbot", id=123456))
    return ch


class TestTelegramGroupPolicy:
    def test_open_requires_mention_by_default(self):
        ch = _tg_channel(group_policy="open")
        assert ch._should_respond_in_group("hello", "-100123") is False
        assert ch._should_respond_in_group("@testbot hello", "-100123") is True

    def test_open_allows_all(self):
        ch = _tg_channel(group_policy="open", group_require_mention=False)
        assert ch._should_respond_in_group("hello", "-100123") is True

    def test_disabled_blocks_all(self):
        ch = _tg_channel(group_policy="disabled")
        assert ch._should_respond_in_group("hello", "-100123") is False

    def test_allowlist_allows_listed_group(self):
        ch = _tg_channel(group_policy="allowlist", group_allow_from=["-100123"], group_require_mention=False)
        assert ch._should_respond_in_group("hello", "-100123") is True

    def test_allowlist_blocks_unlisted_group(self):
        ch = _tg_channel(group_policy="allowlist", group_allow_from=["-100999"])
        assert ch._should_respond_in_group("hello", "-100123") is False

    def test_mention_responds_when_bot_mentioned(self):
        ch = _tg_channel(group_policy="mention")
        assert ch._should_respond_in_group("@testbot hello", "-100123") is True

    def test_mention_responds_when_mention_entity_targets_bot(self):
        ch = _tg_channel(group_policy="mention")
        message = SimpleNamespace(
            entities=[SimpleNamespace(type="mention", offset=0, length=8)],
            caption_entities=[],
            reply_to_message=None,
        )
        assert ch._should_respond_in_group("@TestBot hello", "-100123", message=message) is True

    def test_mention_responds_when_replying_to_bot(self):
        ch = _tg_channel(group_policy="mention")
        message = SimpleNamespace(
            entities=[],
            caption_entities=[],
            reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=123456, username="testbot")),
        )
        assert ch._should_respond_in_group("hello", "-100123", message=message) is True

    def test_mention_ignores_without_bot_mention(self):
        ch = _tg_channel(group_policy="mention")
        assert ch._should_respond_in_group("hello everyone", "-100123") is False

    def test_mention_ignores_other_user_mention(self):
        ch = _tg_channel(group_policy="mention")
        assert ch._should_respond_in_group("@otheruser hello", "-100123") is False


# ─── Discord ─────────────────────────────────────────────────────────────


def _discord_channel(*, group_policy="mention", group_allow_from=None, group_require_mention=True):
    from lemonclaw.channels.discord import DiscordChannel

    config = DiscordConfig(
        enabled=True,
        token="test-token",
        group_policy=group_policy,
        group_allow_from=group_allow_from or [],
        group_require_mention=group_require_mention,
    )
    ch = DiscordChannel(config, MessageBus())
    ch._bot_user_id = "BOT123"
    ch._http = AsyncMock()
    return ch


class TestDiscordGroupPolicy:
    @pytest.mark.asyncio
    async def test_open_allows_group_message(self):
        ch = _discord_channel(group_policy="open", group_require_mention=False)
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
            "mentions": [],
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_blocks_group_message(self):
        ch = _discord_channel(group_policy="disabled")
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowlist_allows_listed_channel(self):
        ch = _discord_channel(group_policy="allowlist", group_allow_from=["CH1"], group_require_mention=False)
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allowlist_blocks_unlisted_channel(self):
        ch = _discord_channel(group_policy="allowlist", group_allow_from=["CH999"])
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_responds_when_bot_mentioned(self):
        ch = _discord_channel(group_policy="mention")
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "<@BOT123> hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
            "mentions": [{"id": "BOT123"}],
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_awaited_once()
        # Verify bot mention was stripped from content
        call_kwargs = ch._handle_message.await_args.kwargs
        assert "<@BOT123>" not in call_kwargs["content"]

    @pytest.mark.asyncio
    async def test_mention_ignores_without_bot_mention(self):
        ch = _discord_channel(group_policy="mention")
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "hello everyone",
            "guild_id": "GUILD1",
            "id": "MSG1",
            "mentions": [],
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_ignores_other_user_mention(self):
        ch = _discord_channel(group_policy="mention")
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "<@OTHER456> hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
            "mentions": [{"id": "OTHER456"}],
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_accepts_reply_to_bot_message(self):
        ch = _discord_channel(group_policy="mention")
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "CH1",
            "content": "hello",
            "guild_id": "GUILD1",
            "id": "MSG1",
            "mentions": [],
            "referenced_message": {"id": "BOTMSG1", "author": {"id": "BOT123"}},
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dm_bypasses_group_policy(self):
        """DM (no guild_id) should not be affected by group_policy=disabled."""
        ch = _discord_channel(group_policy="disabled")
        ch._handle_message = AsyncMock()
        payload = {
            "author": {"id": "USER1", "bot": False},
            "channel_id": "DM1",
            "content": "hello",
            "id": "MSG1",
            # No guild_id = DM
        }
        await ch._handle_message_create(payload)
        ch._handle_message.assert_awaited_once()


# ─── QQ ─────────────────────────────────────────────────────────────────


def _qq_channel(*, group_policy="mention", group_allow_from=None, group_require_mention=True):
    from lemonclaw.channels.qq import QQChannel

    config = QQConfig(
        enabled=True,
        app_id="app",
        secret="secret",
        group_policy=group_policy,
        group_allow_from=group_allow_from or [],
        group_require_mention=group_require_mention,
    )
    ch = QQChannel(config, MessageBus())
    return ch


class TestQQGroupPolicy:
    @pytest.mark.asyncio
    async def test_group_at_event_allows_listed_group(self):
        ch = _qq_channel(group_policy="allowlist", group_allow_from=["GROUP1"])
        ch._handle_message = AsyncMock()
        data = SimpleNamespace(
            id="MSG1",
            content="@bot hello",
            group_openid="GROUP1",
            author=SimpleNamespace(member_openid="USER1"),
            message_reference=SimpleNamespace(message_id="ROOT1"),
        )
        await ch._on_message(data)
        ch._handle_message.assert_awaited_once()
        kwargs = ch._handle_message.await_args.kwargs
        assert kwargs["chat_id"] == "GROUP1"
        assert kwargs["sender_id"] == "USER1"
        assert kwargs["metadata"]["qq"]["is_group"] is True

    @pytest.mark.asyncio
    async def test_group_at_event_blocks_unlisted_group(self):
        ch = _qq_channel(group_policy="allowlist", group_allow_from=["OTHER"])
        ch._handle_message = AsyncMock()
        data = SimpleNamespace(
            id="MSG1",
            content="@bot hello",
            group_openid="GROUP1",
            author=SimpleNamespace(member_openid="USER1"),
            message_reference=SimpleNamespace(message_id="ROOT1"),
        )
        await ch._on_message(data)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_uses_group_api_when_metadata_marks_group(self):
        ch = _qq_channel()
        api = SimpleNamespace(
            post_group_message=AsyncMock(),
            post_c2c_message=AsyncMock(),
        )
        ch._client = SimpleNamespace(api=api)
        from lemonclaw.bus.events import OutboundMessage

        await ch.send(
            OutboundMessage(
                channel="qq",
                chat_id="GROUP1",
                content="hello",
                metadata={"qq": {"is_group": True, "reply_to": "MSG1"}},
            )
        )

        api.post_group_message.assert_awaited_once()
        api.post_c2c_message.assert_not_awaited()


# ─── WhatsApp ────────────────────────────────────────────────────────────


def _whatsapp_channel(*, group_policy="mention", group_allow_from=None, group_require_mention=True):
    config = WhatsAppConfig(
        enabled=True,
        bridge_url="ws://localhost:3001",
        group_policy=group_policy,
        group_allow_from=group_allow_from or [],
        group_require_mention=group_require_mention,
    )
    from lemonclaw.channels.whatsapp import WhatsAppChannel

    ch = WhatsAppChannel(config, MessageBus())
    ch._remember_bot_account({"id": "1234567890:1@s.whatsapp.net", "phone": "1234567890"})
    return ch


class TestWhatsAppGroupPolicy:
    @pytest.mark.asyncio
    async def test_open_allows_group_message(self):
        ch = _whatsapp_channel(group_policy="open", group_require_mention=False)
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_blocks_group_message(self):
        ch = _whatsapp_channel(group_policy="disabled")
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowlist_allows_listed_group_jid(self):
        ch = _whatsapp_channel(
            group_policy="allowlist",
            group_allow_from=["120363xxx@g.us"],
            group_require_mention=False,
        )
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allowlist_blocks_unlisted_group_jid(self):
        ch = _whatsapp_channel(
            group_policy="allowlist",
            group_allow_from=["999999@g.us"],
        )
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_accepts_group_when_bridge_reports_bot_mention(self):
        ch = _whatsapp_channel(group_policy="mention")
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "@1234567890 hello",
            "isGroup": True,
            "id": "MSG1",
            "mentions": ["1234567890@s.whatsapp.net"],
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mention_accepts_reply_to_bot(self):
        ch = _whatsapp_channel(group_policy="mention")
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
            "quotedParticipant": "1234567890@s.whatsapp.net",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mention_degrades_when_bot_identity_unknown(self):
        """WhatsApp mention mode still fails loud when bridge status never reported bot identity."""
        ch = _whatsapp_channel(group_policy="mention")
        ch._bot_identity_tokens.clear()
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_not_awaited()
        assert ch._mention_warned is True

    @pytest.mark.asyncio
    async def test_mention_warns_only_once(self):
        """Warn-once flag prevents log spam."""
        ch = _whatsapp_channel(group_policy="mention")
        ch._bot_identity_tokens.clear()
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "120363xxx@g.us",
            "pn": "",
            "content": "hello",
            "isGroup": True,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        await ch._handle_bridge_message(raw)
        assert ch._mention_warned is True
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dm_bypasses_group_policy(self):
        """DM (isGroup=false) should not be affected by group_policy=disabled."""
        ch = _whatsapp_channel(group_policy="disabled")
        ch._handle_message = AsyncMock()
        raw = json.dumps({
            "type": "message",
            "sender": "1234567890@s.whatsapp.net",
            "pn": "1234567890@s.whatsapp.net",
            "content": "hello",
            "isGroup": False,
            "id": "MSG1",
        })
        await ch._handle_bridge_message(raw)
        ch._handle_message.assert_awaited_once()


# ─── Feishu ──────────────────────────────────────────────────────────────


def _feishu_channel(*, group_policy="mention", group_allow_from=None, bot_open_id=None, group_require_mention=True):
    config = FeishuConfig(
        enabled=True,
        app_id="test-app-id",
        app_secret="test-app-secret",
        group_policy=group_policy,
        group_allow_from=group_allow_from or [],
        group_require_mention=group_require_mention,
    )
    from lemonclaw.channels.feishu import FeishuChannel

    ch = FeishuChannel(config, MessageBus())
    ch._bot_open_id = bot_open_id
    ch._loop = AsyncMock()
    return ch


def _feishu_message_event(
    *,
    chat_type="group",
    chat_id="oc_test123",
    content='{"text":"hello"}',
    message_type="text",
    message_id="msg_001",
    sender_open_id="ou_user1",
    mentions=None,
):
    """Build a mock Feishu P2ImMessageReceiveV1 event."""
    sender_id = SimpleNamespace(open_id=sender_open_id)
    sender = SimpleNamespace(sender_id=sender_id, sender_type="user")

    mention_list = []
    if mentions:
        for m in mentions:
            mid = SimpleNamespace(open_id=m)
            mention_list.append(SimpleNamespace(id=mid))

    message = SimpleNamespace(
        chat_type=chat_type,
        chat_id=chat_id,
        content=content,
        message_type=message_type,
        message_id=message_id,
        mentions=mention_list or None,
    )
    event = SimpleNamespace(message=message, sender=sender)
    return SimpleNamespace(event=event)


class TestFeishuGroupPolicy:
    @pytest.mark.asyncio
    async def test_open_allows_group_message(self):
        ch = _feishu_channel(group_policy="open", bot_open_id="ou_bot1", group_require_mention=False)
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="group")
        await ch._on_message(data)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_blocks_group_message(self):
        ch = _feishu_channel(group_policy="disabled", bot_open_id="ou_bot1")
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="group")
        await ch._on_message(data)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowlist_allows_listed_chat(self):
        ch = _feishu_channel(
            group_policy="allowlist",
            group_allow_from=["oc_test123"],
            bot_open_id="ou_bot1",
            group_require_mention=False,
        )
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="group", chat_id="oc_test123")
        await ch._on_message(data)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allowlist_blocks_unlisted_chat(self):
        ch = _feishu_channel(
            group_policy="allowlist",
            group_allow_from=["oc_other999"],
            bot_open_id="ou_bot1",
        )
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="group", chat_id="oc_test123")
        await ch._on_message(data)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_responds_when_bot_mentioned(self):
        ch = _feishu_channel(group_policy="mention", bot_open_id="ou_bot1")
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(
            chat_type="group",
            mentions=["ou_bot1"],
        )
        await ch._on_message(data)
        ch._handle_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mention_ignores_without_bot_mention(self):
        ch = _feishu_channel(group_policy="mention", bot_open_id="ou_bot1")
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="group", mentions=None)
        await ch._on_message(data)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_ignores_other_user_mention(self):
        ch = _feishu_channel(group_policy="mention", bot_open_id="ou_bot1")
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(
            chat_type="group",
            mentions=["ou_other_user"],
        )
        await ch._on_message(data)
        ch._handle_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mention_degrades_when_bot_open_id_unknown(self):
        """When bot open_id is unavailable, mention mode degrades to disabled."""
        ch = _feishu_channel(group_policy="mention", bot_open_id=None)
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="group")
        await ch._on_message(data)
        ch._handle_message.assert_not_awaited()
        assert ch._mention_warned is True

    @pytest.mark.asyncio
    async def test_dm_bypasses_group_policy(self):
        """P2P chat should not be affected by group_policy=disabled."""
        ch = _feishu_channel(group_policy="disabled", bot_open_id="ou_bot1")
        ch._handle_message = AsyncMock()
        ch._add_reaction = AsyncMock()
        data = _feishu_message_event(chat_type="p2p")
        await ch._on_message(data)
        ch._handle_message.assert_awaited_once()
