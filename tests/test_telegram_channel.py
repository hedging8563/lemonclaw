from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.telegram import TelegramChannel
from lemonclaw.config.schema import TelegramConfig


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
    return SimpleNamespace(callback_query=query, effective_user=user)


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
    return SimpleNamespace(callback_query=query, effective_user=user)


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
async def test_send_model_list_attaches_inline_keyboard(telegram_channel: TelegramChannel) -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
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


@pytest.mark.asyncio
async def test_send_model_switched_updates_original_keyboard(telegram_channel: TelegramChannel) -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
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
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(side_effect=RuntimeError("telegram error")),
    )
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
async def test_tool_outbound_does_not_consume_existing_stream(telegram_channel: TelegramChannel) -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        send_document=AsyncMock(),
        send_photo=AsyncMock(),
        send_video=AsyncMock(),
        send_voice=AsyncMock(),
        send_audio=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    telegram_channel._app = SimpleNamespace(bot=bot)
    stream = telegram_channel._get_or_create_stream('12345')
    stream.message_id = 42
    stream.text = 'partial'
    stream.last_sent_text = 'partial'

    await telegram_channel.send(
        OutboundMessage(
            channel='telegram',
            chat_id='12345',
            content='鲨鱼图片来了！',
            media=['https://example.com/shark.jpg'],
            metadata={},
        )
    )

    assert '12345' in telegram_channel._stream_states
    bot.edit_message_text.assert_not_awaited()
    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_final_edit_failure_falls_back_to_fresh_send(telegram_channel: TelegramChannel) -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        send_document=AsyncMock(),
        send_photo=AsyncMock(),
        send_video=AsyncMock(),
        send_voice=AsyncMock(),
        send_audio=AsyncMock(),
        edit_message_text=AsyncMock(side_effect=[RuntimeError('html fail'), RuntimeError('plain fail')]),
        edit_message_reply_markup=AsyncMock(),
    )
    telegram_channel._app = SimpleNamespace(bot=bot)
    stream = telegram_channel._get_or_create_stream('12345')
    stream.message_id = 77

    await telegram_channel.send(
        OutboundMessage(
            channel='telegram',
            chat_id='12345',
            content='完整最终文本',
            metadata={'_final': True},
        )
    )

    assert bot.edit_message_text.await_count == 2
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs['text'] == '完整最终文本'
