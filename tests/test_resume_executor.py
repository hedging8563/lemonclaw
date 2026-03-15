from __future__ import annotations

import asyncio

import pytest

from lemonclaw.providers.base import LLMResponse


@pytest.mark.asyncio
async def test_agent_loop_execute_safe_resume_runs_replayable_resume(make_agent_loop, echo_provider):
    loop, bus = make_agent_loop()
    echo_provider.responses = [LLMResponse(content="resumed ok", tool_calls=[])]

    loop.ledger.ensure_task(
        task_id="task_1",
        session_key="telegram:123",
        agent_id=loop.agent_id,
        mode="chat",
        channel="telegram",
        goal="resume demo",
        status="failed",
        current_stage="error",
        resume_context={
            "channel": "telegram",
            "chat_id": "123",
            "sender_id": "user-1",
            "session_key": "telegram:123",
            "timezone": "Asia/Shanghai",
        },
    )
    step = loop.ledger.start_step("task_1", step_type="tool_call", name="read_file", replayable=True)
    loop.ledger.finish_step(step, status="failed", error="file not found")

    candidate = await loop.execute_safe_resume("task_1", source="test_resume_executor")

    assert candidate is not None
    assert candidate["recommended_action"] == "replay_failed_steps"
    assert candidate["scheduled"] is True

    resume_task = loop._resume_tasks["task_1"]
    await resume_task

    task = loop.ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "completed"
    assert task["current_stage"] == "done"
    assert task["metadata"]["recovery_history"][-1]["action"] == "resume_execute_requested"

    steps = loop.ledger.materialize_steps("task_1")
    assert steps[0]["status"] == "abandoned"
    assert steps[0]["error"] == "superseded by replay resume"

    outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert outbound.channel == "telegram"
    assert outbound.chat_id == "123"
    assert outbound.content == "resumed ok"

    session = loop.sessions.get_or_create("telegram:123")
    assert [msg["role"] for msg in session.messages] == ["assistant"]
    assert session.messages[0]["content"] == "resumed ok"
