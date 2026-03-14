from pathlib import Path

from lemonclaw.agent.tools.task_checkpoint import TaskCheckpointTool
from lemonclaw.ledger.runtime import TaskLedger


def test_task_checkpoint_updates_ledger(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
    )

    tool = TaskCheckpointTool()
    result = __import__("asyncio").run(
        tool.execute(
            stage="verify",
            summary="Waiting for verification",
            last_successful_step="tool_call",
            next_action="check output",
            status="verifying",
            _task_id="task_1",
            _task_ledger=ledger,
        )
    )

    assert "Checkpoint saved" in result
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "verifying"
    assert task["current_stage"] == "verify"
    assert task["last_successful_step"] == "tool_call"
    assert task["metadata"]["next_action"] == "check output"
