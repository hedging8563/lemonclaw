from pathlib import Path
import asyncio

from lemonclaw.agent.tools.task_checkpoint import TaskCheckpointTool
from lemonclaw.ledger.completion_gate import finalize_task
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


def test_task_checkpoint_merges_verification_metadata_without_dropping_existing_fields(tmp_path: Path):
    ledger = TaskLedger(tmp_path)
    ledger.ensure_task(
        task_id="task_1",
        session_key="cli:direct",
        agent_id="default",
        mode="chat",
        channel="cli",
        goal="demo",
        metadata={
            "retrieval": {
                "strategy": "hybrid",
            },
            "existing_flag": True,
        },
    )

    tool = TaskCheckpointTool()
    result = asyncio.run(
        tool.execute(
            stage="verify",
            summary="Checkpoint with verification evidence",
            next_action="review artifact",
            verification_status="accepted",
            acceptance_evidence=[
                {
                    "kind": "artifact_bundle",
                    "status": "accepted",
                    "summary": "bundle exported",
                    "task_id": "task_1",
                }
            ],
            replay_pointer={
                "kind": "task_bundle",
                "task_id": "task_1",
                "step_id": "step_abc",
                "note": "bundle for replay",
            },
            _task_id="task_1",
            _task_ledger=ledger,
        )
    )

    assert "verification=accepted" in result
    assert "evidence=1" in result
    task = ledger.read_task("task_1")
    assert task is not None
    assert task["current_stage"] == "verify"
    assert task["metadata"]["checkpoint_summary"] == "Checkpoint with verification evidence"
    assert task["metadata"]["next_action"] == "review artifact"
    assert task["metadata"]["existing_flag"] is True
    assert task["metadata"]["retrieval"]["strategy"] == "hybrid"
    verification = task["metadata"]["verification"]
    assert verification["verification_status"] == "accepted"
    assert verification["acceptance_evidence"][0]["kind"] == "artifact_bundle"
    assert verification["acceptance_evidence"][0]["status"] == "accepted"
    assert verification["replay_pointer"]["kind"] == "task_bundle"
    assert verification["ui_channel_replay"]["step_id"] == "step_abc"

    gate = finalize_task(ledger, "task_1")
    assert gate is not None
    assert gate.passed is True
    assert gate.verification["acceptance_evidence_summary"]["count"] == 1
    assert gate.verification["surface_replay_pointer"]["kind"] == "task_bundle"
    assert gate.verification["surface_replay_pointer"]["step_id"] == "step_abc"
