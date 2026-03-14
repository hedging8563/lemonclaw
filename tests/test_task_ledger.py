from pathlib import Path

import pytest

from lemonclaw.ledger.runtime import TaskLedger


def test_task_ledger_writes_task_and_steps(tmp_path: Path):
    ledger = TaskLedger(tmp_path)

    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", input_summary='{"path":"x"}')
    ledger.finish_step(step, status="completed")
    ledger.update_task("task_1", status="completed", current_stage="done")

    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "completed"
    assert task["last_successful_step"] == "read_file"

    steps = ledger.read_steps("task_1")
    assert len(steps) == 2
    assert steps[0]["status"] == "running"
    assert steps[1]["status"] == "completed"


def test_task_ledger_materializes_latest_step_state(tmp_path: Path):
    ledger = TaskLedger(tmp_path)

    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", input_summary='{"path":"x"}')
    ledger.finish_step(step, status="failed", error="boom")

    steps = ledger.materialize_steps("task_1")
    assert len(steps) == 1
    assert steps[0]["status"] == "failed"
    assert steps[0]["error"] == "boom"


def test_task_ledger_read_task_view_summarizes_status_counts(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )
    ok_step = ledger.start_step("task_1", step_type="tool_call", name="read_file")
    ledger.finish_step(ok_step, status="completed")
    fail_step = ledger.start_step("task_1", step_type="tool_call", name="write_file")
    ledger.finish_step(fail_step, status="failed", error="boom")

    view = ledger.read_task_view("task_1")
    assert view is not None
    assert view["summary"]["step_count"] == 2
    assert view["summary"]["status_counts"] == {"completed": 1, "failed": 1}


def test_task_ledger_list_tasks_orders_by_updated_at_desc(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_a",
        session_key="cli:a",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="a",
    )
    ledger.ensure_task(
        task_id="task_b",
        session_key="cli:b",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="b",
    )
    ledger.update_task("task_b", status="completed")

    tasks = ledger.list_tasks()
    assert [task["task_id"] for task in tasks] == ["task_b", "task_a"]


def test_task_ledger_rejects_invalid_task_id(tmp_path: Path):
    ledger = TaskLedger(tmp_path)

    assert ledger.is_valid_task_id("task_valid-1") is True
    assert ledger.is_valid_task_id("../etc/passwd") is False

    with pytest.raises(ValueError, match="invalid task_id"):
        ledger.read_task("../etc/passwd")


def test_task_ledger_write_paths_reject_invalid_task_id(tmp_path: Path):
    ledger = TaskLedger(tmp_path)

    with pytest.raises(ValueError, match="invalid task_id"):
        ledger.ensure_task(
            task_id="../etc/passwd",
            session_key="cli:direct",
            agent_id="default",
            mode="chat",
            channel="cli",
            goal="bad",
        )


def test_task_ledger_outbox_roundtrip_and_materialization(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )

    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )
    assert event["status"] == "pending"

    updated = ledger.update_outbox_event(
        event["event_id"],
        status="sent",
        attempts=1,
    )
    assert updated is not None
    assert updated["status"] == "sent"

    events = ledger.list_outbox_events()
    assert len(events) == 1
    assert events[0]["event_id"] == event["event_id"]
    assert events[0]["status"] == "sent"


def test_task_ledger_rejects_invalid_outbox_id(tmp_path: Path):
    ledger = TaskLedger(tmp_path)

    assert ledger.is_valid_outbox_id("ob_valid-1") is True
    assert ledger.is_valid_outbox_id("../etc/passwd") is False

    with pytest.raises(ValueError, match="invalid event_id"):
        ledger.read_outbox_event("../etc/passwd")


def test_task_ledger_read_outbox_event_returns_latest_revision_without_materializing(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )

    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )
    ledger.update_outbox_event(event["event_id"], status="retrying", attempts=1)
    ledger.update_outbox_event(event["event_id"], status="sent", attempts=2)

    latest = ledger.read_outbox_event(event["event_id"])
    assert latest is not None
    assert latest["status"] == "sent"
    assert latest["attempts"] == 2


def test_task_ledger_claims_due_outbox_events_and_reschedules_retry(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )

    pending = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )
    future = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "later"},
        status="retrying",
        next_attempt_at_ms=9_999,
    )

    claimed = ledger.claim_due_outbox_events(limit=10, now_ms=1_000, claim_owner="test-dispatcher")
    assert [event["event_id"] for event in claimed] == [pending["event_id"]]
    assert claimed[0]["status"] == "claimed"
    assert claimed[0]["attempts"] == 1
    assert claimed[0]["metadata"]["claimed_by"] == "test-dispatcher"

    retried = ledger.mark_outbox_retry(
        pending["event_id"],
        error="temporary failure",
        retry_at_ms=2_000,
        max_attempts=3,
    )
    assert retried is not None
    assert retried["status"] == "retrying"
    assert retried["next_attempt_at_ms"] == 2_000

    terminal = ledger.mark_outbox_retry(
        pending["event_id"],
        error="still failing",
        retry_at_ms=3_000,
        max_attempts=1,
    )
    assert terminal is not None
    assert terminal["status"] == "failed"
    assert terminal["next_attempt_at_ms"] is None

    not_due = ledger.claim_due_outbox_events(limit=10, now_ms=1_000)
    assert [event["event_id"] for event in not_due] == []
    assert ledger.read_outbox_event(future["event_id"])["status"] == "retrying"


def test_task_ledger_can_mark_outbox_failed_without_retry(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )
    ledger.claim_due_outbox_events(limit=10, now_ms=1_000, claim_owner="test-dispatcher")

    failed = ledger.mark_outbox_failed(event["event_id"], error="unsupported effect")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["next_attempt_at_ms"] is None
    assert failed["metadata"]["terminal"] is True


def test_task_ledger_request_outbox_retry_clears_manual_review(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
        status="waiting",
        current_stage="waiting_outbox",
        metadata={
            "recovery": {
                "action": "manual_review",
                "manual_review_required": True,
                "source": "watchdog_soft_recovery",
            }
        },
    )
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        error="temporary failure",
    )

    updated = ledger.request_outbox_retry(event["event_id"], source="webui_manual_retry")

    assert updated is not None
    assert updated["status"] == "pending"
    assert updated["error"] is None
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "waiting"
    assert task["metadata"]["recovery"]["action"] == "manual_retry_requested"
    assert task["metadata"]["recovery"]["manual_review_required"] is False


def test_task_ledger_rejects_invalid_step_id_for_outbox_enqueue(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="say hello",
    )

    assert ledger.is_valid_step_id("step_valid-1") is True
    assert ledger.is_valid_step_id("../etc/passwd") is False

    with pytest.raises(ValueError, match="invalid step_id"):
        ledger.enqueue_outbox(
            task_id="task_1",
            step_id="../etc/passwd",
            effect_type="outbound_message",
            target="telegram:123",
            payload={"content": "hello"},
        )


def test_task_ledger_lists_and_marks_stale_tasks(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )

    task = ledger.read_task("task_1")
    assert task is not None
    task["updated_at_ms"] = 1
    ledger._write_json(ledger._task_path("task_1"), task)

    stale = ledger.list_stale_tasks(stale_after_ms=1000)
    assert [item["task_id"] for item in stale] == ["task_1"]

    updated = ledger.mark_task_stale(
        "task_1",
        source="watchdog_soft_recovery",
        reason="no task ledger update for >1s",
        stale_after_ms=1000,
    )
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["current_stage"] == "stale_recovery"
    assert updated["metadata"]["recovery"]["action"] == "mark_failed"
    view = ledger.read_task_view("task_1")
    assert view is not None
    assert view["summary"]["recovery"]["source"] == "watchdog_soft_recovery"
