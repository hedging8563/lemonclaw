from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lemonclaw.channels.agentbridge import AgentBridgeChannel
from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.agent.subagent import SubagentManager
from lemonclaw.bus.queue import MessageBus
from lemonclaw.session.manager import SessionManager


@pytest.mark.asyncio
async def test_subagent_announce_result_preserves_session_key_override(tmp_path: Path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    manager = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

    await manager._announce_result(
        task_id="sub-1",
        label="demo",
        task="do work",
        result="done",
        origin={
            "channel": "telegram",
            "chat_id": "123",
            "session_key": "telegram:123:456",
            "delivery_context": {
                "source_channel": "telegram",
                "source_chat_id": "123",
                "session_key": "telegram:123:456",
                "route": {"reply_to_message_id": 321, "message_thread_id": 456},
            },
            "delivery_policy": {
                "mode": "replace",
                "preserve_message_identity": True,
            },
            "session_context": {
                "session_key": "telegram:123:456",
                "identity": {
                    "channel": "telegram",
                    "account": "",
                    "chat": "123",
                    "thread": "456",
                    "topic": "",
                },
                "timezone": "Asia/Shanghai",
                "run_mode": "interactive",
            },
        },
        status="ok",
    )

    msg = await bus.consume_inbound()
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "system"
    assert msg.chat_id == "telegram:123"
    assert msg.session_key_override == "telegram:123:456"
    assert msg.session_key == "telegram:123:456"
    assert msg.metadata["_delivery_context"]["route"]["message_thread_id"] == 456
    assert msg.metadata["_delivery_policy"]["mode"] == "replace"
    assert msg.metadata["_delivery_policy"]["preserve_message_identity"] is True
    assert msg.metadata["_session_context"]["identity"]["thread"] == "456"
    assert msg.metadata["_session_context"]["run_mode"] == "interactive"


@pytest.mark.asyncio
async def test_agent_loop_system_message_uses_session_key_override(make_agent_loop):
    loop, _bus = make_agent_loop()

    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content="background result",
        metadata={
            "_delivery_context": {
                "source_channel": "telegram",
                "source_chat_id": "123",
                "session_key": "telegram:123:456",
                "route": {"reply_to_message_id": 321, "message_thread_id": 456},
            },
            "_delivery_policy": {
                "mode": "replace",
                "preserve_message_identity": True,
            },
            "_session_context": {
                "session_key": "telegram:123:456",
                "identity": {
                    "channel": "telegram",
                    "account": "",
                    "chat": "123",
                    "thread": "456",
                    "topic": "",
                },
                "timezone": "Asia/Shanghai",
                "run_mode": "interactive",
            },
        },
        session_key_override="telegram:123:456",
    )

    result = await loop._process_message(msg)

    assert result is not None
    assert loop.sessions._load("telegram:123:456") is not None
    assert loop.sessions._load("telegram:123") is None
    assert result.metadata["_delivery_context"]["route"]["message_thread_id"] == 456
    assert result.metadata["_delivery_policy"]["mode"] == "replace"
    assert result.metadata["_session_context"]["identity"]["thread"] == "456"


@pytest.mark.asyncio
async def test_agentbridge_emit_can_skip_duplicate_session_persist(tmp_path: Path):
    bus = MessageBus()
    session_manager = SessionManager(tmp_path)
    channel = AgentBridgeChannel(SimpleNamespace(event_buffer_size=8), bus, session_manager=session_manager)

    event = await channel.emit(
        OutboundMessage(
            channel="agentbridge",
            chat_id="codex:default:dup",
            content="hello",
            metadata={"_agentbridge_skip_session_persist": True},
        ),
        session_key="agentbridge:codex:default:dup",
    )

    assert event["type"] == "outbound"
    session = session_manager.get("agentbridge:codex:default:dup")
    assert session is None or session.messages == []
