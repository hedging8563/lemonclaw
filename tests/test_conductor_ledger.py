from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lemonclaw.bus.events import InboundMessage
from lemonclaw.conductor.types import IntentAnalysis, OrchestrationPlan, OrchestratorPhase, SubTask, TaskComplexity
from lemonclaw.ledger.runtime import TaskLedger


@pytest.mark.asyncio
async def test_orchestrator_updates_ledger_for_complex_task(tmp_path: Path):
    mock_provider = AsyncMock()
    mock_bus = MagicMock()
    mock_registry = MagicMock()
    mock_registry.list_agents.return_value = []

    from lemonclaw.conductor.orchestrator import Orchestrator

    ledger = TaskLedger(tmp_path)
    orch = Orchestrator(mock_provider, mock_bus, mock_registry, ledger=ledger)

    intent = IntentAnalysis(
        complexity=TaskComplexity.MODERATE,
        required_skills=["general"],
        reasoning="test",
        summary="complex task",
    )
    plan = OrchestrationPlan(
        request_id="test123",
        original_message="do complex task",
        intent=intent,
        phase=OrchestratorPhase.SPLITTING,
        subtasks=[SubTask(id="t1", description="part 1")],
    )

    with patch.object(orch, "_analyze", return_value=intent), \
        patch.object(orch, "_split", return_value=plan), \
        patch.object(orch, "_assign", return_value=None), \
        patch.object(orch, "_monitor", return_value=None), \
        patch.object(orch, "_merge", return_value="merged result"):
        msg = InboundMessage(
            channel="test",
            sender_id="user1",
            chat_id="chat1",
            content="complex task",
            metadata={
                "_task_id": "task_abc",
                "_delivery_policy": {
                    "mode": "replace",
                    "preserve_message_identity": True,
                },
                "_session_context": {
                    "session_key": "test:chat1",
                    "identity": {
                        "channel": "test",
                        "account": "",
                        "chat": "chat1",
                        "thread": "",
                        "topic": "",
                    },
                    "timezone": "",
                    "run_mode": "interactive",
                },
            },
        )
        result = await orch.handle_message(msg)

    assert result == "merged result"
    task = ledger.read_task("task_abc")
    assert task is not None
    assert task["status"] == "completed"
    assert task["current_stage"] == "done"
    assert task["resume_context"]["channel"] == "test"
    assert task["resume_context"]["chat_id"] == "chat1"
    assert task["resume_context"]["session_key"] == "test:chat1"
    assert task["resume_context"]["session_context"]["identity"]["channel"] == "test"
    assert task["resume_context"]["session_context"]["run_mode"] == "interactive"
    assert task["resume_context"]["delivery_policy"]["mode"] == "replace"
    assert task["resume_context"]["delivery_policy"]["preserve_message_identity"] is True
    assert task["completion_gate"]["passed"] is True
    view = ledger.read_task_view("task_abc")
    assert view is not None
    assert "conductor" in view["summary"]
    conductor = task["metadata"]["conductor"]
    assert conductor["planner"]["complexity"] == "moderate"
    assert conductor["planner"]["summary"] == "complex task"
    assert conductor["generator"]["subtask_count"] == 1
    assert conductor["evaluator"]["plan_status"] == "not_run"
