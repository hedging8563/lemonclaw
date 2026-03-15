from __future__ import annotations

import pytest

from lemonclaw.agent.tools.notify import NotifyTool
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.bus.events import OutboundMessage
from lemonclaw.ledger.runtime import TaskLedger


@pytest.mark.asyncio
async def test_notify_channel_uses_outbound_callback():
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = NotifyTool(send_callback=_send)
    result = await tool.execute(target_type="channel", content="hello", channel="cli", chat_id="direct")

    assert result["ok"] is True
    assert len(sent) == 1
    assert sent[0].content == "hello"


@pytest.mark.asyncio
async def test_notify_webhook_blocks_disallowed_domain():
    tool = NotifyTool(allow_webhook_domains=["hooks.example.com"])
    result = await tool.execute(target_type="webhook", content="hello", webhook_url="https://evil.example.com/hook")
    assert result["ok"] is False
    assert "not allowed" in result["summary"]


def test_notify_resolves_capability():
    tool = NotifyTool()
    assert tool.resolve_capability({"target_type": "channel"}) == "notify.channel.send"
    assert tool.resolve_capability({"target_type": "webhook"}) == "notify.webhook.send"


@pytest.mark.asyncio
async def test_notify_prefers_per_call_default_context_over_instance_context():
    sent: list[OutboundMessage] = []

    async def _send(msg: OutboundMessage) -> None:
        sent.append(msg)

    tool = NotifyTool(send_callback=_send)
    tool.set_context("old", "stale")

    result = await tool.execute(
        target_type="channel",
        content="hello",
        _default_channel="fresh",
        _default_chat_id="target",
    )

    assert result["ok"] is True
    assert sent[0].channel == "fresh"
    assert sent[0].chat_id == "target"


@pytest.mark.asyncio
async def test_notify_channel_enqueues_outbox_when_enabled(tmp_path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )

    tool = NotifyTool()
    result = await tool.execute(
        target_type="channel",
        content="hello",
        channel="telegram",
        chat_id="123",
        _task_id="task_1",
        _task_ledger=ledger,
        _step_id="step_notify_1",
        _outbox_enabled=True,
    )

    assert result["ok"] is True
    assert result["raw"]["queued"] is True
    assert result["step_status"] == "waiting_outbox"
    events = ledger.list_outbox_events()
    assert len(events) == 1
    assert events[0]["effect_type"] == "outbound_message"
    assert events[0]["payload"]["channel"] == "telegram"


@pytest.mark.asyncio
async def test_notify_webhook_enqueues_outbox_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )

    monkeypatch.setattr("lemonclaw.agent.tools.notify._validate_url", lambda _url: (True, None, "203.0.113.10"))
    tool = NotifyTool(allow_webhook_domains=["hooks.example.com"])
    result = await tool.execute(
        target_type="webhook",
        content="hello",
        webhook_url="https://hooks.example.com/hook",
        _task_id="task_1",
        _task_ledger=ledger,
        _step_id="step_notify_1",
        _outbox_enabled=True,
    )

    assert result["ok"] is True
    assert result["raw"]["queued"] is True
    assert result["step_status"] == "waiting_outbox"
    events = ledger.list_outbox_events()
    assert len(events) == 1
    assert events[0]["effect_type"] == "webhook_json"
    assert events[0]["target"] == "https://hooks.example.com/hook"


@pytest.mark.asyncio
async def test_tool_registry_passes_step_id_to_notify_outbox(tmp_path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    registry = ToolRegistry(ledger=ledger)
    registry.register(NotifyTool())

    result = await registry.execute(
        "notify",
        {"target_type": "channel", "content": "hello", "channel": "telegram", "chat_id": "123"},
        context={"_task_id": "task_1", "_task_ledger": ledger, "_outbox_enabled": True},
    )

    assert '"queued": true' in result.lower()
    events = ledger.list_outbox_events()
    assert len(events) == 1
    assert events[0]["step_id"].startswith("step_")
    steps = ledger.materialize_steps("task_1")
    assert len(steps) == 1
    assert steps[0]["status"] == "waiting_outbox"
