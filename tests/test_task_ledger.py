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
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="failed", error="terminal delivery failure")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
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
    assert task["metadata"]["recovery_history"][-1]["action"] == "manual_retry_requested"
    steps = ledger.materialize_steps("task_1")
    assert steps[0]["status"] == "waiting_outbox"
    assert steps[0]["error"] is None


def test_task_ledger_request_outbox_retry_uses_retrying_for_previously_attempted_event(tmp_path: Path):
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
    )
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        attempts=1,
        error="temporary failure",
    )

    updated = ledger.request_outbox_retry(event["event_id"], source="webui_manual_retry")

    assert updated is not None
    assert updated["status"] == "retrying"
    assert updated["next_attempt_at_ms"] is not None


def test_task_ledger_request_outbox_retry_is_debounced_for_quick_repeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    )
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        attempts=1,
        error="temporary failure",
    )

    monkeypatch.setattr("lemonclaw.ledger.runtime._now_ms", lambda: 10_000)
    first = ledger.request_outbox_retry(event["event_id"], source="webui_manual_retry")
    assert first is not None
    assert first["status"] == "retrying"

    monkeypatch.setattr("lemonclaw.ledger.runtime._now_ms", lambda: 10_500)
    second = ledger.request_outbox_retry(event["event_id"], source="webui_manual_retry")
    assert second is not None
    assert second["updated_at_ms"] == first["updated_at_ms"]
    assert second["metadata"]["manual_retry_requested_at_ms"] == first["metadata"]["manual_retry_requested_at_ms"]


def test_task_ledger_request_outbox_retry_debounces_claimed_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    )
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="claimed",
        attempts=1,
        metadata={"manual_retry_requested_at_ms": 10_000},
    )

    monkeypatch.setattr("lemonclaw.ledger.runtime._now_ms", lambda: 10_500)
    same = ledger.request_outbox_retry(event["event_id"], source="webui_manual_retry")

    assert same is not None
    assert same["status"] == "claimed"
    assert same["metadata"]["manual_retry_requested_at_ms"] == 10_000


def test_task_ledger_compact_outbox_keeps_nonterminal_and_recent_terminal(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )

    sent_old = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:1",
        payload={"content": "old"},
    )
    ledger.update_outbox_event(sent_old["event_id"], status="sent")
    old_record = ledger.read_outbox_event(sent_old["event_id"])
    old_record["updated_at_ms"] = 1
    ledger._append_jsonl(ledger._outbox_path(), old_record)

    sent_recent = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:2",
        payload={"content": "recent"},
    )
    ledger.update_outbox_event(sent_recent["event_id"], status="sent")

    pending = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:3",
        payload={"content": "pending"},
        status="retrying",
        next_attempt_at_ms=9_999,
    )

    result = ledger.compact_outbox(keep_terminal=0, min_terminal_age_ms=1_000, now_ms=2_000)

    assert result["before"] == 3
    assert result["after"] == 1
    events = ledger.list_outbox_events(limit=10)
    assert {event["event_id"] for event in events} == {pending["event_id"]}


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
    assert updated["metadata"]["recovery_history"][-1]["action"] == "mark_failed"
    view = ledger.read_task_view("task_1")
    assert view is not None
    assert view["summary"]["recovery"]["source"] == "watchdog_soft_recovery"
    assert view["summary"]["recovery_history_count"] == 1


def test_task_ledger_marks_active_tasks_for_process_restart(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_run",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="run",
        status="running",
        current_stage="execute",
    )
    ledger.ensure_task(
        task_id="task_wait",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="wait",
        status="waiting",
        current_stage="waiting_outbox",
    )

    marked = ledger.mark_tasks_for_process_restart(
        source="watchdog_hard_recovery",
        reason="hard recovery for tests",
    )

    assert {task["task_id"] for task in marked} == {"task_run", "task_wait"}
    run_task = ledger.read_task("task_run")
    wait_task = ledger.read_task("task_wait")
    assert run_task["status"] == "failed"
    assert run_task["current_stage"] == "hard_recovery"
    assert run_task["metadata"]["recovery"]["source"] == "watchdog_hard_recovery"
    assert run_task["metadata"]["recovery_history"][-1]["action"] == "mark_failed"
    assert wait_task["status"] == "waiting"
    assert wait_task["metadata"]["recovery"]["action"] == "process_restart_review"
    assert wait_task["metadata"]["recovery"]["manual_review_required"] is True
    assert wait_task["metadata"]["recovery_history"][-1]["action"] == "process_restart_review"


def test_task_ledger_request_task_resume_sets_resume_from_step(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="resume demo",
        status="failed",
        current_stage="execute",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="failed", error="boom")

    resumed = ledger.request_task_resume("task_1", source="webui_task_resume")

    assert resumed is not None
    assert resumed["status"] == "waiting"
    assert resumed["current_stage"] == "resume_requested"
    assert resumed["resume_from_step"] == step.step_id
    assert resumed["metadata"]["recovery"]["action"] == "resume_requested"
    assert resumed["metadata"]["recovery_history"][-1]["action"] == "resume_requested"


def test_task_ledger_build_resume_candidate_prefers_failed_outbox_retry(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="resume demo",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="delivery failed")
    ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        error="boom",
    )

    candidate = ledger.build_resume_candidate("task_1")

    assert candidate is not None
    assert candidate["recommended_action"] == "retry_outbox"
    assert candidate["safe_to_execute"] is True


def test_task_ledger_execute_safe_resume_retries_failed_outbox(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="resume demo",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="notify")
    ledger.finish_step(step, status="waiting_outbox", error="delivery failed")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        attempts=1,
        error="boom",
    )

    candidate = ledger.execute_safe_resume("task_1", source="webui_safe_resume_execute")

    assert candidate is not None
    updated = ledger.read_outbox_event(event["event_id"])
    assert updated is not None
    assert updated["status"] == "retrying"
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["metadata"]["recovery_history"][-1]["action"] == "safe_resume_execute"


def test_step_replayable_flag_persisted(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="replay test",
    )
    step_rw = ledger.start_step("task_1", step_type="tool_call", name="http_request", replayable=False)
    step_ro = ledger.start_step("task_1", step_type="tool_call", name="read_file", replayable=True)
    ledger.finish_step(step_rw, status="failed", error="boom")
    ledger.finish_step(step_ro, status="failed", error="boom")

    steps = ledger.materialize_steps("task_1")
    by_name = {s["name"]: s for s in steps}
    assert by_name["http_request"]["replayable"] is False
    assert by_name["read_file"]["replayable"] is True


def test_build_resume_candidate_recommends_replay_for_replayable_failed_steps(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="replay test",
        status="failed",
        current_stage="error",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", replayable=True)
    ledger.finish_step(step, status="failed", error="file not found")

    candidate = ledger.build_resume_candidate("task_1")
    assert candidate is not None
    assert candidate["recommended_action"] == "replay_failed_steps"
    assert candidate["safe_to_execute"] is True
    assert candidate["replayable_failed_count"] == 1


def test_build_resume_candidate_blocks_replay_for_non_replayable_steps(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="replay test",
        status="failed",
        current_stage="error",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="http_request", replayable=False)
    ledger.finish_step(step, status="failed", error="timeout")

    candidate = ledger.build_resume_candidate("task_1")
    assert candidate is not None
    assert candidate["recommended_action"] == "manual_resume"
    assert candidate["safe_to_execute"] is False
    assert candidate["non_replayable_failed_count"] == 1


def test_execute_safe_resume_rejects_replayable_failed_steps_until_executor_exists(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="replay test",
        status="failed",
        current_stage="error",
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="web_search", replayable=True)
    ledger.finish_step(step, status="failed", error="network error")

    with pytest.raises(ValueError, match="resume executor is wired"):
        ledger.execute_safe_resume("task_1", source="test")
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "error"
    steps = ledger.materialize_steps("task_1")
    assert steps[0]["status"] == "failed"


def test_prepare_replay_failed_steps_supersedes_old_failed_steps(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id="default",
        mode="chat",
        channel="telegram",
        goal="resume demo",
        status="failed",
        current_stage="error",
        resume_context={"channel": "telegram", "chat_id": "123", "session_key": "telegram:123"},
    )
    step = ledger.start_step("task_1", step_type="tool_call", name="read_file", replayable=True)
    ledger.finish_step(step, status="failed", error="file not found")

    prepared = ledger.prepare_replay_failed_steps("task_1", source="test_resume_executor")

    assert prepared is not None
    assert prepared["resume_from_step"] == step.step_id
    steps = ledger.materialize_steps("task_1")
    assert steps[0]["status"] == "abandoned"
    assert steps[0]["error"] == "superseded by replay resume"
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "running"
    assert task["current_stage"] == "resume_queued"
    assert task["metadata"]["recovery"]["action"] == "resume_execute_requested"
