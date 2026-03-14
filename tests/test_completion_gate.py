from pathlib import Path

from lemonclaw.ledger.completion_gate import finalize_task
from lemonclaw.ledger.runtime import TaskLedger


def test_completion_gate_marks_task_completed_when_steps_are_settled(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file")
    ledger.finish_step(step, status="completed")

    result = finalize_task(ledger, "task_1")

    assert result is not None
    assert result.passed is True
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "completed"
    assert task["current_stage"] == "done"
    assert task["completion_gate"]["passed"] is True


def test_completion_gate_blocks_completion_when_outbox_is_pending(tmp_path: Path):
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
        payload={"content": "hello"},
    )

    result = finalize_task(ledger, "task_1")

    assert result is not None
    assert result.passed is False
    assert result.next_status == "waiting"
    assert event["event_id"] in result.open_outbox
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "waiting"
    assert task["current_stage"] == "waiting_outbox"
    assert task["completion_gate"]["passed"] is False


def test_completion_gate_keeps_failed_outbox_in_waiting_for_retry(tmp_path: Path):
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
        payload={"content": "hello"},
        status="failed",
        error="403 forbidden",
    )

    result = finalize_task(ledger, "task_1")

    assert result is not None
    assert result.passed is False
    assert result.next_status == "waiting"
    assert event["event_id"] in result.open_outbox
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "waiting"
    assert task["current_stage"] == "waiting_outbox"
    assert task["completion_gate"]["reason"].startswith("failed outbox events remain")


def test_completion_gate_fails_closed_when_evaluation_raises(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file")
    ledger.finish_step(step, status="completed")
    original = ledger.materialize_steps
    try:
        ledger.materialize_steps = lambda _task_id: (_ for _ in ()).throw(ValueError("corrupt step log"))  # type: ignore[method-assign]
        result = finalize_task(ledger, "task_1")
    finally:
        ledger.materialize_steps = original  # type: ignore[method-assign]

    assert result is not None
    assert result.passed is False
    assert result.next_status == "failed"
    assert "corrupt step log" in result.reason
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "error"


def test_completion_gate_returns_none_for_missing_task(tmp_path: Path):
    ledger = TaskLedger(tmp_path)

    assert finalize_task(ledger, "task_missing") is None
