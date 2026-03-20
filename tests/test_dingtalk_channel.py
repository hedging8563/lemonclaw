from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import asyncio

from lemonclaw.bus.events import OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.dingtalk import DingTalkChannel, LemonClawDingTalkHandler
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


@pytest.mark.asyncio
async def test_dingtalk_handler_keeps_file_only_message() -> None:
    channel = DingTalkChannel(DingTalkConfig(enabled=True, client_id="cid", client_secret="secret"), MessageBus())
    channel._on_message = AsyncMock()

    class _FakeChatbotMessage:
        message_type = "file"
        text = None
        sender_staff_id = "staff1"
        sender_id = "staff1"
        sender_nick = "Alice"
        message_id = "msg1"
        session_webhook = "https://example.invalid/webhook"
        conversation_id = "conv1"
        conversation_type = "1"
        is_in_at_list = False

        @classmethod
        def from_dict(cls, _data):
            return cls()

    import lemonclaw.channels.dingtalk as dingtalk_module

    old_chatbot = dingtalk_module.ChatbotMessage
    old_ack = dingtalk_module.AckMessage
    dingtalk_module.ChatbotMessage = _FakeChatbotMessage
    dingtalk_module.AckMessage = SimpleNamespace(STATUS_OK="OK")
    try:
        handler = LemonClawDingTalkHandler(channel)
        status, text = await handler.process(
            SimpleNamespace(data={"msgtype": "file", "content": {"fileName": "roman-history.docx", "downloadCode": "d1"}})
        )
    finally:
        dingtalk_module.ChatbotMessage = old_chatbot
        dingtalk_module.AckMessage = old_ack

    assert status == "OK"
    assert text == "OK"
    await asyncio.sleep(0)
    channel._on_message.assert_awaited_once()
    args = channel._on_message.await_args.args
    assert args[0] == "[attachment: roman-history.docx]"
