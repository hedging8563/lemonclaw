from pathlib import Path

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
