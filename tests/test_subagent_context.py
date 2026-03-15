from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lemonclaw.agent.subagent import SubagentManager
from lemonclaw.bus.events import InboundMessage
from lemonclaw.bus.queue import MessageBus


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
        origin={"channel": "telegram", "chat_id": "123", "session_key": "telegram:123:456"},
        status="ok",
    )

    msg = await bus.consume_inbound()
    assert isinstance(msg, InboundMessage)
    assert msg.channel == "system"
    assert msg.chat_id == "telegram:123"
    assert msg.session_key_override == "telegram:123:456"
    assert msg.session_key == "telegram:123:456"


@pytest.mark.asyncio
async def test_agent_loop_system_message_uses_session_key_override(make_agent_loop):
    loop, _bus = make_agent_loop()

    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="telegram:123",
        content="background result",
        session_key_override="telegram:123:456",
    )

    result = await loop._process_message(msg)

    assert result is not None
    assert loop.sessions._load("telegram:123:456") is not None
    assert loop.sessions._load("telegram:123") is None
