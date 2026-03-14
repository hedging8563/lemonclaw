from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lemonclaw.bus.queue import MessageBus
from lemonclaw.channels.feishu import FeishuChannel
from lemonclaw.config.schema import FeishuConfig


def _feishu_event(
    *,
    message_id: str = "om_123",
    text: str = "继续",
    chat_type: str = "p2p",
    msg_type: str = "text",
    parent_id: str | None = None,
    root_id: str | None = None,
):
    message = SimpleNamespace(
        message_id=message_id,
        chat_id="oc_test123",
        chat_type=chat_type,
        message_type=msg_type,
        content=json.dumps({"text": text}, ensure_ascii=False),
        mentions=[],
        parent_id=parent_id,
        root_id=root_id,
    )
    sender = SimpleNamespace(
        sender_type="user",
        sender_id=SimpleNamespace(open_id="ou_user_1"),
    )
    event = SimpleNamespace(message=message, sender=sender)
    return SimpleNamespace(event=event)


@pytest.fixture
def feishu_channel() -> FeishuChannel:
    return FeishuChannel(FeishuConfig(enabled=True, app_id="app", app_secret="secret"), MessageBus())


@pytest.mark.asyncio
async def test_feishu_on_message_dedupes_same_message_id(feishu_channel: FeishuChannel) -> None:
    data = _feishu_event(message_id="om_dup")
    feishu_channel._add_reaction = AsyncMock()
    feishu_channel._handle_message = AsyncMock()

    await feishu_channel._on_message(data)
    await feishu_channel._on_message(data)

    feishu_channel._handle_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_feishu_on_message_includes_reply_context(feishu_channel: FeishuChannel) -> None:
    data = _feishu_event(message_id="om_reply", text="现在继续", parent_id="om_parent")
    feishu_channel._add_reaction = AsyncMock()
    feishu_channel._handle_message = AsyncMock()
    feishu_channel._fetch_reply_context_sync = lambda _message_id: "上一条 Feishu 消息"

    await feishu_channel._on_message(data)

    feishu_channel._handle_message.assert_awaited_once()
    kwargs = feishu_channel._handle_message.await_args.kwargs
    assert kwargs["content"] == "[Reply to: 上一条 Feishu 消息]\n现在继续"
    assert kwargs["metadata"]["parent_id"] == "om_parent"


@pytest.mark.asyncio
async def test_feishu_send_replies_with_image_attachment_when_message_id_present(
    feishu_channel: FeishuChannel, tmp_path
) -> None:
    image_path = tmp_path / "reply.png"
    image_path.write_bytes(b"png")

    feishu_channel._client = SimpleNamespace()
    feishu_channel._upload_image_sync = lambda _path: "img_key"
    feishu_channel._reply_message_sync = lambda message_id, msg_type, content, *, reply_in_thread: (
        message_id == "om_parent" and msg_type == "image" and json.loads(content)["image_key"] == "img_key" and reply_in_thread
    )
    feishu_channel._send_message_sync = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not use create"))

    await feishu_channel.send(
        SimpleNamespace(
            channel="feishu",
            chat_id="oc_test123",
            content="",
            media=[str(image_path)],
            metadata={"message_id": "om_parent", "chat_type": "group"},
        )
    )
