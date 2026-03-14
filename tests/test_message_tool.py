import pytest

from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.channels.delivery_context import DELIVERY_CONTEXT_KEY


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"


@pytest.mark.asyncio
async def test_message_tool_carries_delivery_context_for_same_target() -> None:
    tool = MessageTool()
    turn_state = tool.start_turn()
    tool.set_context(
        "telegram",
        "12345",
        "321",
        {
            "source_channel": "telegram",
            "source_chat_id": "12345",
            "session_key": "telegram:12345",
            "route": {"reply_to_message_id": 321, "message_thread_id": 456},
        },
    )

    sent = []

    async def _send(msg):
        sent.append(msg)

    tool.set_send_callback(_send)

    result = await tool.execute(content="hello", _message_turn_state=turn_state)

    assert result == "Message sent to telegram:12345"
    assert len(sent) == 1
    assert sent[0].metadata[DELIVERY_CONTEXT_KEY]["route"]["reply_to_message_id"] == 321
    assert turn_state["sent"] is True
    assert turn_state["messages"] == sent


@pytest.mark.asyncio
async def test_message_tool_does_not_carry_delivery_context_for_different_target() -> None:
    tool = MessageTool()
    turn_state = tool.start_turn()
    tool.set_context(
        "telegram",
        "12345",
        "321",
        {
            "source_channel": "telegram",
            "source_chat_id": "12345",
            "session_key": "telegram:12345",
            "route": {"reply_to_message_id": 321},
        },
    )

    sent = []

    async def _send(msg):
        sent.append(msg)

    tool.set_send_callback(_send)

    result = await tool.execute(
        content="hello",
        channel="telegram",
        chat_id="99999",
        _message_turn_state=turn_state,
    )

    assert result == "Message sent to telegram:99999"
    assert len(sent) == 1
    assert DELIVERY_CONTEXT_KEY not in sent[0].metadata
    assert turn_state["sent"] is False
    assert turn_state["messages"] == []


def test_message_tool_start_turn_returns_isolated_state() -> None:
    first = MessageTool.start_turn()
    second = MessageTool.start_turn()

    first["sent"] = True
    first["messages"].append("x")

    assert second == {"sent": False, "messages": []}
