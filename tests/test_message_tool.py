import pytest

from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.channels.delivery_context import DELIVERY_CONTEXT_KEY, DELIVERY_POLICY_KEY
from lemonclaw.channels.session_context import SESSION_CONTEXT_KEY
from lemonclaw.ledger.runtime import TaskLedger


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert "active conversation target" in result
    assert "channel and chat_id" in result


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
async def test_message_tool_carries_delivery_policy_for_same_target() -> None:
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
        {
            "mode": "replace",
            "preserve_message_identity": True,
        },
    )

    sent = []

    async def _send(msg):
        sent.append(msg)

    tool.set_send_callback(_send)

    result = await tool.execute(content="hello", _message_turn_state=turn_state)

    assert result == "Message sent to telegram:12345"
    assert len(sent) == 1
    assert sent[0].metadata[DELIVERY_POLICY_KEY]["mode"] == "replace"
    assert sent[0].metadata[DELIVERY_POLICY_KEY]["preserve_message_identity"] is True


@pytest.mark.asyncio
async def test_message_tool_carries_session_context_for_same_target() -> None:
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
        {
            "mode": "replace",
            "preserve_message_identity": True,
        },
        {
            "session_key": "telegram:12345",
            "identity": {
                "channel": "telegram",
                "account": "",
                "chat": "12345",
                "thread": "456",
                "topic": "",
            },
            "timezone": "Asia/Shanghai",
            "run_mode": "interactive",
        },
    )

    sent = []

    async def _send(msg):
        sent.append(msg)

    tool.set_send_callback(_send)

    result = await tool.execute(content="hello", _message_turn_state=turn_state)

    assert result == "Message sent to telegram:12345"
    assert len(sent) == 1
    assert sent[0].metadata[SESSION_CONTEXT_KEY]["identity"]["thread"] == "456"
    assert sent[0].metadata[SESSION_CONTEXT_KEY]["run_mode"] == "interactive"


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


@pytest.mark.asyncio
async def test_message_tool_does_not_carry_delivery_policy_for_different_target() -> None:
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
        {
            "mode": "final_only",
            "preserve_message_identity": True,
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
    assert DELIVERY_POLICY_KEY not in sent[0].metadata
    assert turn_state["sent"] is False
    assert turn_state["messages"] == []


@pytest.mark.asyncio
async def test_message_tool_does_not_carry_session_context_for_different_target() -> None:
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
        {
            "mode": "final_only",
            "preserve_message_identity": True,
        },
        {
            "session_key": "telegram:12345",
            "identity": {
                "channel": "telegram",
                "account": "",
                "chat": "12345",
                "thread": "456",
                "topic": "",
            },
            "timezone": "Asia/Shanghai",
            "run_mode": "interactive",
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
    assert SESSION_CONTEXT_KEY not in sent[0].metadata
    assert turn_state["sent"] is False
    assert turn_state["messages"] == []


def test_message_tool_start_turn_returns_isolated_state() -> None:
    first = MessageTool.start_turn()
    second = MessageTool.start_turn()

    first["sent"] = True
    first["messages"].append("x")

    assert second == {"sent": False, "messages": []}


@pytest.mark.asyncio
async def test_message_tool_enqueues_outbox_when_enabled(tmp_path) -> None:
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
        {
            "mode": "replace",
            "preserve_message_identity": True,
        },
        {
            "session_key": "telegram:12345",
            "identity": {
                "channel": "telegram",
                "account": "",
                "chat": "12345",
                "thread": "456",
                "topic": "",
            },
            "timezone": "Asia/Shanghai",
            "run_mode": "interactive",
        },
    )
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:12345",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="notify",
    )

    result = await tool.execute(
        content="hello",
        _message_turn_state=turn_state,
        _task_id="task_1",
        _task_ledger=ledger,
        _step_id="step_msg_1",
        _outbox_enabled=True,
    )

    assert result["ok"] is True
    assert result["raw"]["queued"] is True
    assert result["step_status"] == "waiting_outbox"
    events = ledger.list_outbox_events()
    assert len(events) == 1
    assert events[0]["effect_type"] == "outbound_message"
    assert events[0]["payload"]["channel"] == "telegram"
    assert events[0]["payload"]["metadata"][DELIVERY_POLICY_KEY]["mode"] == "replace"
    assert events[0]["payload"]["metadata"][SESSION_CONTEXT_KEY]["identity"]["thread"] == "456"
    assert turn_state["sent"] is True
