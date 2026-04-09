from pathlib import Path

from lemonclaw.ledger.migrate import migrate_json_to_sqlite
from lemonclaw.ledger.runtime import TaskLedger
from lemonclaw.ledger.sqlite_store import SQLiteTaskLedger


def test_task_ledger_auto_selects_sqlite_for_fresh_workspace(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    assert ledger.backend == "sqlite"


def test_task_ledger_auto_selects_json_when_legacy_state_exists(tmp_path: Path):
    state_dir = tmp_path / ".lemonclaw-state" / "tasks"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "task_legacy.json").write_text("{}", encoding="utf-8")

    ledger = TaskLedger(tmp_path)
    assert ledger.backend == "json"


def test_sqlite_task_and_step_roundtrip(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="sqlite")

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

    steps = ledger.materialize_steps("task_1")
    assert len(steps) == 1
    assert steps[0]["status"] == "completed"
    assert steps[0]["replayable"] is True


def test_sqlite_outbox_claim_retry_and_compact(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="sqlite")
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="deliver",
    )

    pending = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )
    old_terminal = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "old"},
        status="sent",
        attempts=1,
    )
    recent_terminal = ledger.enqueue_outbox(
        task_id="task_1",
        step_id="step_notify",
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "recent"},
        status="failed",
        attempts=2,
    )

    claimed = ledger.claim_due_outbox_events(limit=10, now_ms=ledger.now_ms(), claim_owner="sqlite-test")
    assert [event["event_id"] for event in claimed] == [pending["event_id"]]
    retried = ledger.mark_outbox_retry(
        pending["event_id"],
        error="temporary failure",
        retry_at_ms=ledger.now_ms() + 1000,
        max_attempts=3,
    )
    assert retried is not None
    assert retried["status"] == "retrying"

    compacted = ledger.compact_outbox(
        keep_terminal=1,
        min_terminal_age_ms=1,
        now_ms=ledger.now_ms() + 10_000,
    )
    assert compacted["before"] == 3
    assert compacted["after"] == 2

    events = ledger.materialize_outbox_events()
    event_ids = {event["event_id"] for event in events}
    terminal_ids = {
        event["event_id"]
        for event in events
        if str(event.get("status") or "") in {"sent", "failed", "compensated"}
    }
    assert pending["event_id"] in event_ids
    assert len(terminal_ids) == 1
    assert terminal_ids.issubset({old_terminal["event_id"], recent_terminal["event_id"]})


def test_sqlite_resume_candidate_prefers_failed_outbox_retry_and_executes(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="sqlite")
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="notify user",
    )
    step = ledger.start_step("task_1", step_type="outbox", name="notify")
    ledger.finish_step(step, status="waiting_outbox")
    event = ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="failed",
        attempts=1,
        error="network",
    )

    candidate = ledger.build_resume_candidate("task_1")
    assert candidate is not None
    assert candidate["recommended_action"] == "retry_outbox"
    assert candidate["safe_to_execute"] is True

    post = ledger.execute_safe_resume("task_1", source="sqlite-test")
    updated = ledger.read_outbox_event(event["event_id"])

    assert post is not None
    assert updated is not None
    assert updated["status"] == "retrying"
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["current_stage"] == "waiting_outbox"


def test_sqlite_can_reclaim_stale_claimed_outbox_event(tmp_path: Path):
    ledger = TaskLedger(tmp_path, backend="sqlite")
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="reclaim stale claim",
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
        metadata={"claimed_at_ms": 1_000, "claimed_by": "dead-dispatcher"},
    )

    reclaimed = ledger.reclaim_stale_claimed_outbox_events(
        stale_after_ms=30_000,
        source="sqlite-dispatcher",
        now_ms=40_000,
    )

    assert [item["event_id"] for item in reclaimed] == [event["event_id"]]
    updated = ledger.read_outbox_event(event["event_id"])
    assert updated is not None
    assert updated["status"] == "retrying"
    assert updated["next_attempt_at_ms"] is not None


def test_migrate_json_to_sqlite_preserves_task_steps_and_outbox(tmp_path: Path):
    json_ledger = TaskLedger(tmp_path, backend="json")
    json_ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="migrate me",
        status="waiting",
        current_stage="waiting_outbox",
    )
    step = json_ledger.start_step("task_1", step_type="tool_call", name="notify")
    json_ledger.finish_step(step, status="waiting_outbox")
    event = json_ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
        status="retrying",
        attempts=1,
        next_attempt_at_ms=12345,
    )
    json_ledger.update_task("task_1", completion_gate={"passed": False, "reason": "pending outbox"})

    result = migrate_json_to_sqlite(tmp_path)
    assert result == {"tasks": 1, "step_events": 2, "outbox_events": 1, "skipped": False, "dry_run": False}

    auto_ledger = TaskLedger(tmp_path)
    assert auto_ledger.backend == "sqlite"
    task = auto_ledger.read_task("task_1")
    assert task is not None
    assert task["completion_gate"]["passed"] is False
    assert task["current_stage"] == "waiting_outbox"

    steps = auto_ledger.read_steps("task_1")
    assert len(steps) == 2
    assert auto_ledger.materialize_steps("task_1")[0]["status"] == "waiting_outbox"

    migrated_event = auto_ledger.read_outbox_event(event["event_id"])
    assert migrated_event is not None
    assert migrated_event["status"] == "retrying"
    assert migrated_event["next_attempt_at_ms"] == 12345


def test_migrate_json_to_sqlite_dry_run_reports_counts_without_writing(tmp_path: Path):
    json_ledger = TaskLedger(tmp_path, backend="json")
    json_ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="dry run",
    )
    step = json_ledger.start_step("task_1", step_type="tool_call", name="notify")
    json_ledger.finish_step(step, status="completed")
    json_ledger.enqueue_outbox(
        task_id="task_1",
        step_id=step.step_id,
        effect_type="outbound_message",
        target="telegram:123",
        payload={"content": "hello"},
    )

    result = migrate_json_to_sqlite(tmp_path, dry_run=True)

    assert result == {"tasks": 1, "step_events": 2, "outbox_events": 1, "skipped": False, "dry_run": True}
    sqlite_ledger = SQLiteTaskLedger(tmp_path)
    assert sqlite_ledger.has_any_data() is False
