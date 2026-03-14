import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.delivery_context import DELIVERY_CONTEXT_KEY
from lemonclaw.channels.manager import ChannelManager
from lemonclaw.config.schema import Config


def test_activity_session_key_includes_message_thread_id() -> None:
    msg = OutboundMessage(
        channel="telegram",
        chat_id="-100123",
        content="hello",
        metadata={"message_thread_id": 456},
    )

    assert ChannelManager._activity_session_key(msg) == "telegram:-100123:456"


def test_telegram_progress_is_not_skipped_from_manager_broadcast() -> None:
    progress = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="partial",
        metadata={"_progress": True, "_chunk": True},
    )
    final = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="final",
        metadata={"_final": True},
    )
    regular = OutboundMessage(
        channel="telegram",
        chat_id="12345",
        content="regular",
        metadata={},
    )

    assert ChannelManager._should_skip_activity_broadcast(progress) is False
    assert ChannelManager._should_skip_activity_broadcast(final) is False
    assert ChannelManager._should_skip_activity_broadcast(regular) is False


def test_thinking_is_skipped_from_manager_broadcast() -> None:
    thinking = OutboundMessage(
        channel="feishu",
        chat_id="ou_xxx",
        content="internal reasoning",
        metadata={"_progress": True, "_thinking": True},
    )

    assert ChannelManager._should_skip_activity_broadcast(thinking) is True


def test_thinking_and_chunk_are_internal_messages() -> None:
    thinking = OutboundMessage(channel="discord", chat_id="1", content="thinking", metadata={"_progress": True, "_thinking": True})
    chunk = OutboundMessage(channel="discord", chat_id="1", content="chunk", metadata={"_progress": True, "_chunk": True})

    assert ChannelManager._is_internal_message(thinking) is True
    assert ChannelManager._is_internal_message(chunk) is True


def test_tool_start_and_result_are_internal_messages() -> None:
    tool_start = OutboundMessage(channel="feishu", chat_id="ou_xxx", content='{"name":"web_search"}', metadata={"_progress": True, "_tool_start": True})
    tool_result = OutboundMessage(channel="feishu", chat_id="ou_xxx", content='{"name":"web_search","result":"ok"}', metadata={"_progress": True, "_tool_result": True})

    assert ChannelManager._is_internal_message(tool_start) is True
    assert ChannelManager._is_internal_message(tool_result) is True


@pytest.mark.asyncio
async def test_manager_suppresses_progress_delivery_to_im_channels() -> None:
    bus = MessageBus()
    manager = ChannelManager(Config(), bus)
    fake_channel = SimpleNamespace(send=AsyncMock())
    manager.channels["telegram"] = fake_channel

    dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    await bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="working...",
            metadata={"_progress": True},
        )
    )
    await asyncio.sleep(0.05)
    dispatch_task.cancel()
    await dispatch_task

    fake_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_applies_delivery_route_before_send() -> None:
    bus = MessageBus()
    manager = ChannelManager(Config(), bus)
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    manager.channels["telegram"] = SimpleNamespace(send=AsyncMock(side_effect=_send))

    dispatch_task = asyncio.create_task(manager._dispatch_outbound())
    await bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="12345",
            content="hello",
            metadata={
                DELIVERY_CONTEXT_KEY: {
                    "source_channel": "telegram",
                    "source_chat_id": "12345",
                    "session_key": "telegram:12345:456",
                    "route": {"reply_to_message_id": 321, "message_thread_id": 456},
                }
            },
        )
    )
    await asyncio.sleep(0.05)
    dispatch_task.cancel()
    await dispatch_task

    assert len(sent) == 1
    assert sent[0].metadata["message_id"] == 321
    assert sent[0].metadata["message_thread_id"] == 456
