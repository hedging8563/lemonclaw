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
