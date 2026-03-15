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


@pytest.mark.asyncio
async def test_agent_loop_execute_safe_resume_rolls_back_when_dispatch_spawn_fails(make_agent_loop, monkeypatch):
    loop, _bus = make_agent_loop()

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
        },
    )
    step = loop.ledger.start_step("task_1", step_type="tool_call", name="read_file", replayable=True)
    loop.ledger.finish_step(step, status="failed", error="file not found")

    monkeypatch.setattr(loop, "_spawn_dispatch_task", lambda _msg: (_ for _ in ()).throw(RuntimeError("loop closed")))

    with pytest.raises(ValueError, match="resume dispatch failed: loop closed"):
        await loop.execute_safe_resume("task_1", source="test_resume_executor")

    task = loop.ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    assert task["current_stage"] == "error"
    assert task["metadata"]["recovery"]["action"] == "resume_dispatch_failed"
    steps = loop.ledger.materialize_steps("task_1")
    assert steps[0]["status"] == "failed"
    assert steps[0]["error"] == "file not found"


@pytest.mark.asyncio
async def test_agent_loop_execute_safe_resume_rejects_cron_task_without_explicit_target(make_agent_loop):
    loop, _bus = make_agent_loop()

    loop.ledger.ensure_task(
        task_id="task_1",
        session_key="cron:job-1",
        agent_id="cron",
        mode="cron",
        channel="cli",
        goal="resume cron",
        status="failed",
        current_stage="error",
        resume_context={
            "channel": "cli",
            "chat_id": "direct",
            "sender_id": "cron",
            "session_key": "cron:job-1",
            "auto_resume_allowed": False,
            "resume_disabled_reason": "cron job has no explicit delivery target; resume requires operator review",
        },
    )
    step = loop.ledger.start_step("task_1", step_type="cron_job", name="nightly", replayable=True)
    loop.ledger.finish_step(step, status="failed", error="network error")

    with pytest.raises(ValueError, match="cron job has no explicit delivery target"):
        await loop.execute_safe_resume("task_1", source="test_resume_executor")

    task = loop.ledger.read_task("task_1")
    assert task is not None
    assert task["status"] == "failed"
    steps = loop.ledger.materialize_steps("task_1")
    assert steps[0]["status"] == "failed"
