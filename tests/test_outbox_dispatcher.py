from pathlib import Path

import pytest

from lemonclaw.ledger.outbox import OutboxDispatcher
from lemonclaw.ledger.runtime import TaskLedger


@pytest.mark.asyncio
async def test_outbox_dispatcher_delivers_and_finalizes_task(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="completed")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"channel": "telegram", "chat_id": "123", "content": "hello"},
    )
    delivered: list[str] = []

    async def _deliver(outbox_event: dict) -> None:
        delivered.append(str(outbox_event["event_id"]))

    dispatcher = OutboxDispatcher(ledger, _deliver, retry_delay_ms=10, max_attempts=3)
    count = await dispatcher.dispatch_once()

    assert count == 1
    assert delivered == [event["event_id"]]
    assert ledger.read_outbox_event(event["event_id"])["status"] == "sent"
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "completed"
    assert task["completion_gate"]["passed"] is True


@pytest.mark.asyncio
async def test_outbox_dispatcher_retries_then_leaves_task_waiting(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="completed")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"channel": "telegram", "chat_id": "123", "content": "hello"},
    )

    async def _deliver(_outbox_event: dict) -> None:
        raise RuntimeError("temporary failure")

    dispatcher = OutboxDispatcher(ledger, _deliver, retry_delay_ms=10, max_attempts=1)
    count = await dispatcher.dispatch_once()

    assert count == 0
    failed = ledger.read_outbox_event(event["event_id"])
    assert failed is not None
    assert failed["status"] == "failed"
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "waiting"
    assert task["current_stage"] == "waiting_outbox"
    assert task["completion_gate"]["reason"].startswith("failed outbox events remain")
