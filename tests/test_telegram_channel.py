from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.telegram import TelegramChannel
from lemonclaw.config.schema import TelegramConfig
from lemonclaw.triggers import TriggerRuntime


@pytest.fixture
def telegram_channel() -> TelegramChannel:
    return TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus())


def _group_callback_update(data: str, *, thread_id: int | None = 456, message_id: int = 321):
    user = SimpleNamespace(id=42, username="alice", first_name="Alice")
    chat = SimpleNamespace(id=-100123, type="supergroup")
    message = SimpleNamespace(chat_id=chat.id, chat=chat, message_id=message_id, message_thread_id=thread_id)
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(update_id=1001, callback_query=query, effective_user=user)


def _private_callback_update(data: str, *, message_id: int = 321):
    user = SimpleNamespace(id=7, username="bob", first_name="Bob")
    chat = SimpleNamespace(id=12345, type="private")
    message = SimpleNamespace(chat_id=chat.id, chat=chat, message_id=message_id)
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(update_id=1002, callback_query=query, effective_user=user)


def _private_text_update(
    text: str,
    *,
    message_id: int = 321,
    reply_text: str | None = None,
    reply_message_id: int = 111,
):
    user = SimpleNamespace(id=7, username="bob", first_name="Bob")
    chat = SimpleNamespace(id=12345, type="private")
    reply_to_message = None
    if reply_text is not None:
        reply_to_message = SimpleNamespace(
            message_id=reply_message_id,
            text=reply_text,
            caption=None,
            photo=None,
            voice=None,
            audio=None,
            document=None,
            video=None,
            sticker=None,
        )
    message = SimpleNamespace(
        chat_id=chat.id,
        chat=chat,
        message_id=message_id,
        text=text,
        caption=None,
        photo=None,
        voice=None,
        audio=None,
        document=None,
        reply_to_message=reply_to_message,
    )
    return SimpleNamespace(update_id=2001, message=message, effective_user=user)


def _group_sender_chat_update(text: str, *, message_id: int = 4001):
    chat = SimpleNamespace(id=-1003819834760, type="supergroup")
    sender_chat = SimpleNamespace(id=-1003819834760, title="dicloak ai运营团队", username=None, type="supergroup")
    message = SimpleNamespace(
        chat_id=chat.id,
        chat=chat,
        message_id=message_id,
        text=text,
        caption=None,
        photo=None,
        voice=None,
        audio=None,
        document=None,
        reply_to_message=None,
        entities=[],
        caption_entities=[],
        sender_chat=sender_chat,
        from_user=None,
    )
    return SimpleNamespace(update_id=3001, message=message, effective_user=None)


def _group_user_update(text: str, *, message_id: int = 4002):
    user = SimpleNamespace(id=999999999, username="outsider", first_name="Outsider")
    chat = SimpleNamespace(id=-1003819834760, type="supergroup")
    message = SimpleNamespace(
        chat_id=chat.id,
        chat=chat,
        message_id=message_id,
        text=text,
        caption=None,
        photo=None,
        voice=None,
        audio=None,
        document=None,
        reply_to_message=None,
        entities=[],
        caption_entities=[],
        sender_chat=None,
        from_user=user,
    )
    return SimpleNamespace(update_id=3004, message=message, effective_user=user)


def _group_sender_chat_command_update(text: str, *, message_id: int = 5001):
    chat = SimpleNamespace(id=-1003819834760, type="supergroup")
    sender_chat = SimpleNamespace(id=-1003819834760, title="dicloak ai运营团队", username=None, type="supergroup")
    message = SimpleNamespace(
        chat_id=chat.id,
        chat=chat,
        message_id=message_id,
        text=text,
        sender_chat=sender_chat,
        from_user=None,
        entities=[],
        caption_entities=[],
    )
    return SimpleNamespace(update_id=3002, message=message, effective_user=None)


def _channel_post_sender_chat_update(text: str, *, message_id: int = 6001):
    chat = SimpleNamespace(id=-1003819834760, type="supergroup")
    sender_chat = SimpleNamespace(id=-1003819834760, title="dicloak ai运营团队", username=None, type="supergroup")
    message = SimpleNamespace(
        chat_id=chat.id,
        chat=chat,
        message_id=message_id,
        text=text,
        caption=None,
        photo=None,
        voice=None,
        audio=None,
        document=None,
        reply_to_message=None,
        entities=[],
        caption_entities=[],
        sender_chat=sender_chat,
        from_user=None,
    )
    return SimpleNamespace(update_id=3003, channel_post=message, effective_user=None)


def _bot_stub(**overrides):
    base = {
        "send_message": AsyncMock(),
        "send_message_draft": AsyncMock(),
        "send_document": AsyncMock(),
        "send_photo": AsyncMock(),
        "send_video": AsyncMock(),
        "send_voice": AsyncMock(),
        "send_audio": AsyncMock(),
        "edit_message_reply_markup": AsyncMock(),
        "send_chat_action": AsyncMock(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_model_callback_close_removes_keyboard(telegram_channel: TelegramChannel) -> None:
    update = _private_callback_update("model:close")
    telegram_channel._handle_message = AsyncMock()

    await telegram_channel._on_model_callback(update, None)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    telegram_channel._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_callback_close_ignores_keyboard_edit_failure(telegram_channel: TelegramChannel) -> None:
    update = _private_callback_update("model:close")
    update.callback_query.edit_message_reply_markup = AsyncMock(side_effect=RuntimeError("telegram error"))
    telegram_channel._handle_message = AsyncMock()

    await telegram_channel._on_model_callback(update, None)

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_reply_markup.assert_awaited_once_with(reply_markup=None)
    telegram_channel._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_callback_forwards_model_switch_with_topic_metadata(telegram_channel: TelegramChannel) -> None:
    update = _group_callback_update("model:gpt-5.2", thread_id=456, message_id=999)
    telegram_channel._handle_message = AsyncMock()

    await telegram_channel._on_model_callback(update, None)

    update.callback_query.answer.assert_awaited_once()
    telegram_channel._handle_message.assert_awaited_once_with(
        sender_id="42|alice",
        chat_id="-100123",
        content="/model gpt-5.2",
        metadata={
            "user_id": 42,
            "username": "alice",
            "first_name": "Alice",
            "is_group": True,
            "_callback_message_id": 999,
            "message_thread_id": 456,
        },
        session_key="telegram:-100123:456",
    )


@pytest.mark.asyncio
async def test_model_callback_forwards_private_chat_without_thread_metadata(telegram_channel: TelegramChannel) -> None:
    update = _private_callback_update("model:claude-sonnet-4-6", message_id=888)
    telegram_channel._handle_message = AsyncMock()

    await telegram_channel._on_model_callback(update, None)

    telegram_channel._handle_message.assert_awaited_once_with(
        sender_id="7|bob",
        chat_id="12345",
        content="/model claude-sonnet-4-6",
        metadata={
            "user_id": 7,
            "username": "bob",
            "first_name": "Bob",
            "is_group": False,
            "_callback_message_id": 888,
        },
        session_key=None,
    )


@pytest.mark.asyncio
async def test_telegram_inbound_records_poll_trigger(tmp_path) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="test-token"),
        MessageBus(),
        trigger_runtime=trigger_runtime,
    )
    channel._handle_message = AsyncMock()

    await channel._on_message(_private_text_update("hello"), None)

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    trigger_id = kwargs["metadata"]["_trigger_id"]
    assert kwargs["metadata"]["_trigger_source"] == "poll.telegram"
    assert kwargs["metadata"]["_trigger_kind"] == "message.private"
    record = trigger_runtime.read_trigger(trigger_id)
    assert record is not None
    assert record["source"] == "poll.telegram"
    assert record["kind"] == "message.private"
    assert record["chat_id"] == "12345"


@pytest.mark.asyncio
async def test_start_polling_keeps_backlog_by_default(monkeypatch) -> None:
    poll_kwargs: dict[str, object] = {}

    class FakeBot:
        username = "lemonclaw"

        async def get_me(self):
            return SimpleNamespace(username=self.username)

        async def set_my_commands(self, _commands):
            return None

    class FakeUpdater:
        async def start_polling(self, **kwargs):
            poll_kwargs.update(kwargs)
            channel._running = False

        async def stop(self):
            return None

    class FakeApp:
        def __init__(self) -> None:
            self.bot = FakeBot()
            self.updater = FakeUpdater()

        def add_error_handler(self, _handler):
            return None

        def add_handler(self, _handler):
            return None

        async def initialize(self):
            return None

        async def start(self):
            return None

        async def stop(self):
            return None

        async def shutdown(self):
            return None

    class FakeBuilder:
        def token(self, _token):
            return self

        def request(self, _request):
            return self

        def get_updates_request(self, _request):
            return self

        def proxy(self, _proxy):
            return self

        def get_updates_proxy(self, _proxy):
            return self

        def build(self):
            return FakeApp()

    monkeypatch.setattr("lemonclaw.channels.telegram.HTTPXRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr("lemonclaw.channels.telegram.Application.builder", lambda: FakeBuilder())

    channel = TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus())
    await channel.start()

    assert poll_kwargs["drop_pending_updates"] is False
    assert poll_kwargs["allowed_updates"] == [
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "callback_query",
    ]


@pytest.mark.asyncio
async def test_start_polling_can_opt_in_to_dropping_backlog(monkeypatch) -> None:
    poll_kwargs: dict[str, object] = {}

    class FakeBot:
        username = "lemonclaw"

        async def get_me(self):
            return SimpleNamespace(username=self.username)

        async def set_my_commands(self, _commands):
            return None

    class FakeUpdater:
        async def start_polling(self, **kwargs):
            poll_kwargs.update(kwargs)
            channel._running = False

        async def stop(self):
            return None

    class FakeApp:
        def __init__(self) -> None:
            self.bot = FakeBot()
            self.updater = FakeUpdater()

        def add_error_handler(self, _handler):
            return None

        def add_handler(self, _handler):
            return None

        async def initialize(self):
            return None

        async def start(self):
            return None

        async def stop(self):
            return None

        async def shutdown(self):
            return None

    class FakeBuilder:
        def token(self, _token):
            return self

        def request(self, _request):
            return self

        def get_updates_request(self, _request):
            return self

        def proxy(self, _proxy):
            return self

        def get_updates_proxy(self, _proxy):
            return self

        def build(self):
            return FakeApp()

    monkeypatch.setattr("lemonclaw.channels.telegram.HTTPXRequest", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr("lemonclaw.channels.telegram.Application.builder", lambda: FakeBuilder())

    channel = TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus())
    await channel.start(drop_pending_updates=True)

    assert poll_kwargs["drop_pending_updates"] is True


@pytest.mark.asyncio
async def test_on_message_includes_reply_context_for_text_reply(telegram_channel: TelegramChannel) -> None:
    update = _private_text_update("现在继续", reply_text="上一条消息内容")
    telegram_channel._handle_message = AsyncMock()

    await telegram_channel._on_message(update, None)

    telegram_channel._handle_message.assert_awaited_once()
    kwargs = telegram_channel._handle_message.await_args.kwargs
    assert kwargs["content"] == "[Reply to: 上一条消息内容]\n现在继续"
    assert kwargs["metadata"]["reply_to_message_id"] == 111


@pytest.mark.asyncio
async def test_on_message_accepts_group_sender_chat_without_effective_user(telegram_channel: TelegramChannel) -> None:
    update = _group_sender_chat_update("@dic_supperpower_bot 继续")
    telegram_channel._handle_message = AsyncMock()
    telegram_channel._app = SimpleNamespace(bot=SimpleNamespace(username="dic_supperpower_bot", id=8573580959))
    telegram_channel.config.group_policy = "allowlist"
    telegram_channel.config.group_require_mention = True
    telegram_channel.config.group_allow_from = ["-1003819834760"]

    await telegram_channel._on_message(update, None)

    telegram_channel._handle_message.assert_awaited_once()
    kwargs = telegram_channel._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "-1003819834760|dicloak ai运营团队"
    assert kwargs["chat_id"] == "-1003819834760"
    assert kwargs["content"] == "继续"
    assert kwargs["metadata"]["sender_chat_title"] == "dicloak ai运营团队"
    assert kwargs["metadata"]["sender_chat_type"] == "supergroup"


@pytest.mark.asyncio
async def test_forward_command_accepts_group_sender_chat_without_effective_user(telegram_channel: TelegramChannel) -> None:
    update = _group_sender_chat_command_update("/model@dic_supperpower_bot gpt-5.4")
    telegram_channel._handle_message = AsyncMock()
    telegram_channel._app = SimpleNamespace(bot=SimpleNamespace(username="dic_supperpower_bot", id=8573580959))
    telegram_channel.config.group_policy = "allowlist"
    telegram_channel.config.group_require_mention = True
    telegram_channel.config.group_allow_from = ["-1003819834760"]

    await telegram_channel._forward_command(update, None)

    telegram_channel._handle_message.assert_awaited_once()
    kwargs = telegram_channel._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "-1003819834760|dicloak ai运营团队"
    assert kwargs["chat_id"] == "-1003819834760"
    assert kwargs["content"] == "/model@dic_supperpower_bot gpt-5.4"


@pytest.mark.asyncio
async def test_on_message_accepts_channel_post_sender_chat_without_effective_user(telegram_channel: TelegramChannel) -> None:
    update = _channel_post_sender_chat_update("@dic_supperpower_bot 群里继续")
    telegram_channel._handle_message = AsyncMock()
    telegram_channel._app = SimpleNamespace(bot=SimpleNamespace(username="dic_supperpower_bot", id=8573580959))
    telegram_channel.config.group_policy = "allowlist"
    telegram_channel.config.group_require_mention = True
    telegram_channel.config.group_allow_from = ["-1003819834760"]

    await telegram_channel._on_message(update, None)

    telegram_channel._handle_message.assert_awaited_once()
    kwargs = telegram_channel._handle_message.await_args.kwargs
    assert kwargs["sender_id"] == "-1003819834760|dicloak ai运营团队"
    assert kwargs["chat_id"] == "-1003819834760"
    assert kwargs["content"] == "群里继续"


@pytest.mark.asyncio
async def test_group_message_bypasses_dm_pairing_allowlist(telegram_channel: TelegramChannel) -> None:
    update = _group_user_update("@dic_supperpower_bot 在吗")
    telegram_channel._app = SimpleNamespace(bot=SimpleNamespace(username="dic_supperpower_bot", id=8573580959))
    telegram_channel.config.dm_policy = "pairing"
    telegram_channel.config.allow_from = ["5215352940"]
    telegram_channel.config.group_policy = "allowlist"
    telegram_channel.config.group_require_mention = True
    telegram_channel.config.group_allow_from = ["-1003819834760"]
    telegram_channel.bus.publish_inbound = AsyncMock()

    await telegram_channel._on_message(update, None)

    telegram_channel.bus.publish_inbound.assert_awaited_once()
    inbound = telegram_channel.bus.publish_inbound.await_args.args[0]
    assert inbound.chat_id == "-1003819834760"
    assert inbound.sender_id == "999999999|outsider"
    assert inbound.content == "在吗"


@pytest.mark.asyncio
async def test_send_model_list_attaches_inline_keyboard(telegram_channel: TelegramChannel) -> None:
    bot = _bot_stub()
    telegram_channel._app = SimpleNamespace(bot=bot)

    await telegram_channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="Available models (use /model <name> to switch)",
            metadata={"_command": "model_list", "_current_model": "claude-sonnet-4-6"},
        )
    )

    bot.send_message.assert_awaited_once()
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 12345
    assert kwargs["reply_markup"] is not None
    assert "Select model" in kwargs["text"]
    assert "Source:" not in kwargs["text"]
    button_texts = [
        button.text
        for row in kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert not any(text in {"👑 Flagship", "⚡ Standard", "💡 Economy", "🔬 Specialist"} for text in button_texts)
    assert not any(button.callback_data == "noop" for row in kwargs["reply_markup"].inline_keyboard for button in row)
    bot.send_message_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_model_switched_updates_original_keyboard(telegram_channel: TelegramChannel) -> None:
    bot = _bot_stub()
    telegram_channel._app = SimpleNamespace(bot=bot)

    await telegram_channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="Switched to GPT-5.2",
            metadata={
                "_command": "model_switched",
                "_current_model": "gpt-5.2",
                "_callback_message_id": 777,
            },
        )
    )

    bot.send_message.assert_awaited_once()
    bot.edit_message_reply_markup.assert_awaited_once()
    kwargs = bot.edit_message_reply_markup.await_args.kwargs
    assert kwargs["chat_id"] == 12345
    assert kwargs["message_id"] == 777
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_send_model_switched_ignores_keyboard_update_failure(telegram_channel: TelegramChannel) -> None:
    bot = _bot_stub(edit_message_reply_markup=AsyncMock(side_effect=RuntimeError("telegram error")))
    telegram_channel._app = SimpleNamespace(bot=bot)

    await telegram_channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="Switched to GPT-5.2",
            metadata={
                "_command": "model_switched",
                "_current_model": "gpt-5.2",
                "_callback_message_id": 777,
            },
        )
    )

    bot.send_message.assert_awaited_once()
    bot.edit_message_reply_markup.assert_awaited_once()


@pytest.mark.asyncio
async def test_progress_messages_are_noop_for_telegram_draft_mode(telegram_channel: TelegramChannel) -> None:
    bot = _bot_stub()
    telegram_channel._app = SimpleNamespace(bot=bot)

    await telegram_channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="partial chunk",
            metadata={"_progress": True, "_chunk": True},
        )
    )

    bot.send_message.assert_not_awaited()
    bot.send_message_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_send_does_not_use_draft_streaming(telegram_channel: TelegramChannel) -> None:
    bot = _bot_stub()
    telegram_channel._app = SimpleNamespace(bot=bot)

    await telegram_channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="鲨鱼图片来了！",
            media=["https://example.com/shark.jpg"],
            metadata={},
        )
    )

    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    bot.send_message_draft.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_final_message_does_not_emit_false_activity_error() -> None:
    activity_bus = SimpleNamespace(broadcast=AsyncMock())
    channel = TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus(), activity_bus=activity_bus)
    bot = _bot_stub()
    channel._app = SimpleNamespace(bot=bot)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="",
            metadata={"_final": True},
        )
    )

    bot.send_message_draft.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    activity_bus.broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_message_sends_single_committed_message() -> None:
    activity_bus = SimpleNamespace(broadcast=AsyncMock())
    channel = TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus(), activity_bus=activity_bus)
    bot = _bot_stub()
    channel._app = SimpleNamespace(bot=bot)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="x" * 100,
            metadata={"_final": True},
        )
    )

    bot.send_message.assert_awaited_once()
    bot.send_message_draft.assert_not_awaited()
    activity_bus.broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_message_stops_typing_and_skips_draft_preview() -> None:
    activity_bus = SimpleNamespace(broadcast=AsyncMock())
    channel = TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus(), activity_bus=activity_bus)
    bot = _bot_stub()
    channel._app = SimpleNamespace(bot=bot)
    channel._typing_tasks["12345"] = asyncio.create_task(asyncio.sleep(60))

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="完整最终文本",
            metadata={"_final": True},
        )
    )

    bot.send_message.assert_awaited_once()
    bot.send_message_draft.assert_not_awaited()
    activity_bus.broadcast.assert_not_awaited()
    assert "12345" not in channel._typing_tasks


@pytest.mark.asyncio
async def test_final_message_propagates_message_thread_id_without_draft() -> None:
    activity_bus = SimpleNamespace(broadcast=AsyncMock())
    channel = TelegramChannel(TelegramConfig(enabled=True, token="test-token"), MessageBus(), activity_bus=activity_bus)
    bot = _bot_stub()
    channel._app = SimpleNamespace(bot=bot)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="-100123",
            content="topic reply",
            metadata={"_final": True, "message_thread_id": 456},
        )
    )

    assert bot.send_message.await_args.kwargs["message_thread_id"] == 456
    bot.send_message_draft.assert_not_awaited()
    activity_bus.broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_split_video_uses_async_to_thread(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[list[str]] = []
    source = tmp_path / 'clip.mp4'
    source.write_bytes(b'x' * (60 * 1024 * 1024))

    async def fake_to_thread(func, *args, **kwargs):
        if func is os.path.getsize:
            return source.stat().st_size
        cmd = args[0]
        if cmd[0] == 'ffprobe':
            return SimpleNamespace(returncode=0, stdout='12.0\n')
        out_path = cmd[-1]
        Path(out_path).write_bytes(b'segment')
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(asyncio, 'to_thread', fake_to_thread)

    segments = await TelegramChannel._split_video(str(source))
    assert segments
    assert calls



def test_cleanup_split_tempdirs_only_removes_stale_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    stale = tmp_path / 'lemonclaw_tg_split_old'
    fresh = tmp_path / 'lemonclaw_tg_split_new'
    stale.mkdir()
    fresh.mkdir()
    (stale / 'part1.mp4').write_text('old', encoding='utf-8')
    (fresh / 'part1.mp4').write_text('new', encoding='utf-8')

    monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(tmp_path))
    now = time.time()
    stale_mtime = now - (7 * 60 * 60)
    fresh_mtime = now - 60
    os.utime(stale, (stale_mtime, stale_mtime))
    os.utime(fresh, (fresh_mtime, fresh_mtime))

    TelegramChannel._cleanup_split_tempdirs()

    assert not stale.exists()
    assert fresh.exists()
