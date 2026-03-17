from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.dingtalk import DingTalkChannel
from lemonclaw.config.schema import DingTalkConfig
from lemonclaw.triggers import TriggerRuntime


@pytest.fixture
def dingtalk_channel() -> DingTalkChannel:
    return DingTalkChannel(DingTalkConfig(enabled=True, client_id="cid", client_secret="secret"), MessageBus())


@pytest.mark.asyncio
async def test_dingtalk_group_message_requires_at_flag(dingtalk_channel: DingTalkChannel) -> None:
    dingtalk_channel._handle_message = AsyncMock()

    await dingtalk_channel._on_message(
        "hello group",
        "staff1",
        "Alice",
        metadata={
            "conversation_id": "conv_group_1",
            "conversation_type": "2",
            "is_in_at_list": False,
            "session_webhook": "https://example.invalid/webhook",
        },
    )

    dingtalk_channel._handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_dingtalk_group_message_with_at_uses_conversation_id(dingtalk_channel: DingTalkChannel) -> None:
    dingtalk_channel._handle_message = AsyncMock()

    await dingtalk_channel._on_message(
        "@bot hello group",
        "staff1",
        "Alice",
        metadata={
            "message_id": "msg1",
            "conversation_id": "conv_group_1",
            "conversation_type": "2",
            "is_in_at_list": True,
            "session_webhook": "https://example.invalid/webhook",
        },
    )

    dingtalk_channel._handle_message.assert_awaited_once()
    kwargs = dingtalk_channel._handle_message.await_args.kwargs
    assert kwargs["chat_id"] == "conv_group_1"
    assert kwargs["metadata"]["is_group"] is True
    assert kwargs["metadata"]["dingtalk"]["session_webhook"] == "https://example.invalid/webhook"


@pytest.mark.asyncio
async def test_dingtalk_inbound_records_stream_trigger(tmp_path) -> None:
    trigger_runtime = TriggerRuntime(tmp_path)
    channel = DingTalkChannel(
        DingTalkConfig(enabled=True, client_id="cid", client_secret="secret"),
        MessageBus(),
        trigger_runtime=trigger_runtime,
    )
    channel._handle_message = AsyncMock()

    await channel._on_message(
        "hello private",
        "staff1",
        "Alice",
        metadata={
            "message_id": "msg1",
            "conversation_id": "staff1",
            "conversation_type": "1",
        },
    )

    channel._handle_message.assert_awaited_once()
    kwargs = channel._handle_message.await_args.kwargs
    trigger_id = kwargs["metadata"]["_trigger_id"]
    assert kwargs["metadata"]["_trigger_source"] == "stream.dingtalk"
    assert kwargs["metadata"]["_trigger_kind"] == "chatbot.message.private"
    record = trigger_runtime.read_trigger(trigger_id)
    assert record is not None
    assert record["source"] == "stream.dingtalk"
    assert record["kind"] == "chatbot.message.private"
    assert record["chat_id"] == "staff1"


@pytest.mark.asyncio
async def test_dingtalk_send_prefers_session_webhook(dingtalk_channel: DingTalkChannel) -> None:
    dingtalk_channel._http = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda: None)))
    dingtalk_channel._get_access_token = AsyncMock(return_value="token")

    await dingtalk_channel.send(
        OutboundMessage(
            channel="dingtalk",
            chat_id="conv_group_1",
            content="hello group",
            metadata={"dingtalk": {"session_webhook": "https://oapi.dingtalk.com/robot/sendBySession?session=abc"}},
        )
    )

    dingtalk_channel._http.post.assert_awaited_once()
    dingtalk_channel._get_access_token.assert_not_awaited()


@pytest.mark.asyncio
async def test_dingtalk_send_rejects_non_allowlisted_session_webhook(dingtalk_channel: DingTalkChannel) -> None:
    dingtalk_channel._http = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda: None)))
    dingtalk_channel._get_access_token = AsyncMock(return_value="token")

    await dingtalk_channel.send(
        OutboundMessage(
            channel="dingtalk",
            chat_id="conv_group_1",
            content="hello group",
            metadata={"dingtalk": {"session_webhook": "https://example.invalid/webhook"}},
        )
    )

    dingtalk_channel._http.post.assert_not_awaited()
    dingtalk_channel._get_access_token.assert_not_awaited()
