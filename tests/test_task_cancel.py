"""Tests for /stop task cancellation."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = Path(tempfile.mkdtemp(prefix="lemonclaw-task-cancel-"))

    with patch("lemonclaw.agent.loop.ContextBuilder"), \
         patch("lemonclaw.agent.loop.SessionManager"), \
         patch("lemonclaw.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


class TestRuntimeCorrectionClassification:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("Please, stop.", "interrupt"),
            ("Would you please continue?", "continue"),
            ("Only emit the patch, don't commit.", "constraint_patch"),
            ("请停止一下。", "interrupt"),
            ("麻烦继续执行。", "continue"),
            ("只改这一个文件，不要提交。", "constraint_patch"),
            ("改成英文版本。", "correction"),
        ],
    )
    def test_classify_runtime_correction(self, content, expected):
        from lemonclaw.agent.loop import AgentLoop

        assert AgentLoop._classify_runtime_correction(content) == expected


class TestHandleStop:
    @pytest.mark.asyncio
    async def test_stop_no_active_task(self):
        from lemonclaw.bus.events import InboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "No active task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_active_task(self):
        from lemonclaw.bus.events import InboundMessage

        loop, bus = _make_loop()
        cancelled = asyncio.Event()

        async def slow_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = [task]

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        assert cancelled.is_set()
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "stopped" in out.content.lower()

    @pytest.mark.asyncio
    async def test_stop_cancels_multiple_tasks(self):
        from lemonclaw.bus.events import InboundMessage

        loop, bus = _make_loop()
        events = [asyncio.Event(), asyncio.Event()]

        async def slow(idx):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                events[idx].set()
                raise

        tasks = [asyncio.create_task(slow(i)) for i in range(2)]
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = tasks

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        assert all(e.is_set() for e in events)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "2 task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_process_direct_task(self):
        loop, bus = _make_loop()
        started = asyncio.Event()

        async def _slow_process(msg, **kwargs):
            started.set()
            await asyncio.sleep(60)
            raise AssertionError("should have been cancelled")

        loop._process_message = _slow_process
        direct = asyncio.create_task(
            loop.process_direct(
                "long job",
                session_key="test:c1",
                channel="test",
                chat_id="c1",
            )
        )

        await asyncio.wait_for(started.wait(), timeout=1.0)
        result = await loop.stop_session("test:c1", channel="test", chat_id="c1")
        assert result["running"] == 0

        with pytest.raises(asyncio.CancelledError):
            await direct
        assert "test:c1" not in loop._active_tasks
        assert "test:c1" not in loop._stop_events


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_processes_and_publishes(self):
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="hi")
        )
        await loop._dispatch(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "hi"
        task = loop.ledger.read_task(str(msg.metadata["_task_id"]))
        assert task is not None
        assert task["status"] == "completed"
        assert task["completion_gate"]["passed"] is True

    @pytest.mark.asyncio
    async def test_dispatch_keeps_task_waiting_when_outbox_is_pending(self):
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()

        async def _mock_process(m, **kwargs):
            task_id = str(m.metadata["_task_id"])
            step = loop.ledger.start_step(task_id, step_type="tool_call", name="notify")
            loop.ledger.finish_step(step, status="completed")
            loop.ledger.enqueue_outbox(
                task_id=task_id,
                step_id=step.step_id,
                effect_type="outbound_message",
                target="telegram:123",
                payload={"content": "hi"},
            )
            return OutboundMessage(channel="test", chat_id="c1", content="hi")

        loop._process_message = _mock_process
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")

        await loop._dispatch(msg)

        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "hi"
        task = loop.ledger.read_task(str(msg.metadata["_task_id"]))
        assert task is not None
        assert task["status"] == "waiting"
        assert task["current_stage"] == "waiting_outbox"
        assert task["completion_gate"]["passed"] is False

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        order = []

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.content}")
            await asyncio.sleep(0.05)
            order.append(f"end-{m.content}")
            return OutboundMessage(channel="test", chat_id="c1", content=m.content)

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="b")

        t1 = asyncio.create_task(loop._dispatch(msg1))
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.gather(t1, t2)
        assert order == ["start-a", "end-a", "start-b", "end-b"]

    @pytest.mark.asyncio
    async def test_dispatch_cleans_task_tracking_when_cancelled_waiting_for_lock(self):
        from lemonclaw.bus.events import InboundMessage

        loop, _bus = _make_loop()
        loop._process_message = AsyncMock()
        held_lock = asyncio.Lock()
        await held_lock.acquire()
        loop._session_locks["test:c1"] = held_lock

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="blocked")
        dispatch_task = asyncio.create_task(loop._dispatch(msg))

        for _ in range(50):
            if "test:c1" in loop._stop_events and str((msg.metadata or {}).get("_task_id") or ""):
                break
            await asyncio.sleep(0.01)

        task_id = str((msg.metadata or {}).get("_task_id") or "")
        assert task_id
        assert task_id in (loop._active_task_ids.get("test:c1") or set())
        assert "test:c1" in loop._stop_events

        dispatch_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await dispatch_task

        assert loop._active_task_ids.get("test:c1") in (None, set())
        assert "test:c1" not in loop._stop_events
        held_lock.release()

    @pytest.mark.asyncio
    async def test_stop_sets_stop_event(self):
        """Verify /stop sets the cooperative stop_event."""
        from lemonclaw.bus.events import InboundMessage

        loop, bus = _make_loop()
        stop_event = asyncio.Event()
        loop._stop_events["test:c1"] = stop_event

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        assert stop_event.is_set()


class TestSteeringLoop:
    @pytest.mark.asyncio
    async def test_stop_event_breaks_tool_loop(self):
        """Agent loop should exit when stop_event is set between tool calls."""
        from lemonclaw.agent.loop import AgentLoop

        loop, bus = _make_loop()
        stop_event = asyncio.Event()

        # Mock provider to return tool calls
        mock_response = MagicMock()
        mock_response.has_tool_calls = True
        mock_response.content = None
        mock_response.reasoning_content = None
        mock_response.usage = None
        tc = MagicMock()
        tc.id = "tc1"
        tc.name = "exec"
        tc.arguments = {"command": "echo hi"}
        mock_response.tool_calls = [tc]
        loop.provider.chat = AsyncMock(return_value=mock_response)

        # Set stop event before execution
        stop_event.set()

        messages = [{"role": "user", "content": "test"}]
        final, tools_used, _, _ = await loop._run_agent_loop(
            messages, stop_event=stop_event,
        )
        assert final == "⏹ Task stopped."
        assert tools_used == []

    @pytest.mark.asyncio
    async def test_per_session_lock_allows_concurrency(self):
        """Different sessions should not block each other."""
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        order = []

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.sender_id}")
            await asyncio.sleep(0.05)
            order.append(f"end-{m.sender_id}")
            return OutboundMessage(channel="test", chat_id=m.chat_id, content="ok")

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u2", chat_id="c2", content="b")

        t1 = asyncio.create_task(loop._dispatch(msg1))
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.gather(t1, t2)

        # Both should start before either ends (concurrent)
        assert order[0].startswith("start-")
        assert order[1].startswith("start-")

    @pytest.mark.asyncio
    async def test_dispatch_cleans_up_stop_event(self):
        """stop_event should be cleaned up after dispatch completes."""
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="ok")
        )
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hi")
        await loop._dispatch(msg)
        assert "test:c1" not in loop._stop_events

    @pytest.mark.asyncio
    async def test_non_command_follow_up_interrupts_active_task_and_marks_correction(self, make_agent_loop):
        """A new non-command turn should preempt running work in the same session."""
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = make_agent_loop()

        first_started = asyncio.Event()
        first_cancelled = asyncio.Event()
        second_started = asyncio.Event()

        async def fake_process(msg, **kwargs):
            if msg.content == "draft answer":
                first_started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    first_cancelled.set()
                    raise
            if msg.content == "actually, correct that":
                second_started.set()
                return OutboundMessage(channel="test", chat_id="c1", content="updated answer")
            raise AssertionError(f"unexpected content: {msg.content!r}")

        loop._process_message = fake_process

        first_msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="draft answer")
        second_msg = InboundMessage(
            channel="test",
            sender_id="u1",
            chat_id="c1",
            content="actually, correct that",
            metadata={"_delivery_policy": {"mode": "replace", "preserve_message_identity": True}},
        )

        first_task = loop._spawn_dispatch_task(first_msg)
        await asyncio.wait_for(first_started.wait(), timeout=1.0)

        second_task = loop._spawn_dispatch_task(second_msg)

        await asyncio.wait_for(first_cancelled.wait(), timeout=1.0)
        await asyncio.wait_for(second_started.wait(), timeout=1.0)

        outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert outbound.content == "updated answer"

        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1.0)

        first_task_id = str(first_msg.metadata["_task_id"])
        second_task_id = str(second_msg.metadata["_task_id"])

        old_task = loop.ledger.read_task(first_task_id)
        new_task = loop.ledger.read_task(second_task_id)

        assert old_task is not None
        assert old_task["session_key"] == "test:c1"
        assert old_task["status"] in {"abandoned", "cancelled"}
        assert old_task["current_stage"] in {"cancelled", "abandoned"}
        assert old_task["metadata"]["recovery_history"][-1]["action"] == "user_correction_interrupt"

        assert new_task is not None
        assert new_task["session_key"] == "test:c1"
        runtime_correction = new_task["metadata"]["runtime_correction"]
        assert runtime_correction["kind"]
        assert runtime_correction["message_preview"]
        assert first_task_id in runtime_correction["supersedes_task_ids"]
        assert runtime_correction["supersedes_task_stages"] == ["dispatch"]
        assert runtime_correction["interrupted_task_count"] == 1
        assert runtime_correction["delivery_intent"]["delivery_policy"]["mode"] == "replace"
        assert new_task["resume_context"]["runtime_correction"]["kind"] == runtime_correction["kind"]
        assert new_task["resume_context"]["runtime_correction"]["supersedes_task_ids"] == [first_task_id]
        assert new_task["resume_context"]["runtime_correction"]["supersedes_task_stages"] == ["dispatch"]
        assert new_task["resume_context"]["runtime_correction"]["delivery_intent"]["delivery_policy"]["preserve_message_identity"] is True
        assert new_task["metadata"]["recovery_history"][-1]["details"]["supersedes_task_stages"] == ["dispatch"]
        assert new_task["metadata"]["recovery_history"][-1]["details"]["delivery_intent"]["delivery_policy"]["mode"] == "replace"
        assert new_task["metadata"]["recovery_history"][-1]["action"] == "runtime_correction_received"

    @pytest.mark.asyncio
    async def test_non_command_follow_up_interrupts_active_task_and_marks_constraint_patch(self, make_agent_loop):
        """A constraint patch follow-up should persist its runtime-correction kind."""
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = make_agent_loop()

        first_started = asyncio.Event()
        first_cancelled = asyncio.Event()
        second_started = asyncio.Event()

        async def fake_process(msg, **kwargs):
            if msg.content == "draft answer":
                first_started.set()
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    first_cancelled.set()
                    raise
            if msg.content == "please, only patch the text":
                second_started.set()
                return OutboundMessage(channel="test", chat_id="c1", content="patched answer")
            raise AssertionError(f"unexpected content: {msg.content!r}")

        loop._process_message = fake_process

        first_msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="draft answer")
        second_msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="please, only patch the text")

        first_task = loop._spawn_dispatch_task(first_msg)
        await asyncio.wait_for(first_started.wait(), timeout=1.0)

        second_task = loop._spawn_dispatch_task(second_msg)

        await asyncio.wait_for(first_cancelled.wait(), timeout=1.0)
        await asyncio.wait_for(second_started.wait(), timeout=1.0)

        outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert outbound.content == "patched answer"

        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1.0)

        second_task_id = str(second_msg.metadata["_task_id"])
        new_task = loop.ledger.read_task(second_task_id)

        assert new_task is not None
        runtime_correction = new_task["metadata"]["runtime_correction"]
        assert runtime_correction["kind"] == "constraint_patch"
        assert runtime_correction["message_preview"] == "please, only patch the text"
        assert runtime_correction["interrupted_task_count"] == 1
        assert new_task["resume_context"]["runtime_correction"]["kind"] == "constraint_patch"
        assert new_task["metadata"]["recovery_history"][-1]["action"] == "runtime_correction_received"

    @pytest.mark.asyncio
    async def test_continue_follow_up_does_not_interrupt_active_task(self, make_agent_loop):
        """A continue follow-up should queue behind the current task instead of cancelling it."""
        from lemonclaw.bus.events import InboundMessage, OutboundMessage

        loop, bus = make_agent_loop()

        first_started = asyncio.Event()
        allow_first_finish = asyncio.Event()
        first_cancelled = asyncio.Event()
        second_started = asyncio.Event()

        async def fake_process(msg, **kwargs):
            if msg.content == "draft answer":
                first_started.set()
                try:
                    await asyncio.wait_for(allow_first_finish.wait(), timeout=1.0)
                except asyncio.CancelledError:
                    first_cancelled.set()
                    raise
                return OutboundMessage(channel="test", chat_id="c1", content="draft complete")
            if msg.content == "continue with tests":
                second_started.set()
                return OutboundMessage(channel="test", chat_id="c1", content="continued")
            raise AssertionError(f"unexpected content: {msg.content!r}")

        loop._process_message = fake_process

        first_msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="draft answer")
        second_msg = InboundMessage(
            channel="test",
            sender_id="u1",
            chat_id="c1",
            content="continue with tests",
            metadata={"_delivery_policy": {"mode": "final_only", "preserve_message_identity": True}},
        )

        first_task = loop._spawn_dispatch_task(first_msg)
        await asyncio.wait_for(first_started.wait(), timeout=1.0)

        second_task = loop._spawn_dispatch_task(second_msg)
        await asyncio.sleep(0.05)

        assert first_cancelled.is_set() is False
        assert second_started.is_set() is False

        allow_first_finish.set()
        await asyncio.wait_for(second_started.wait(), timeout=1.0)

        first_outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        second_outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert first_outbound.content == "draft complete"
        assert second_outbound.content == "continued"

        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=1.0)

        first_task_id = str(first_msg.metadata["_task_id"])
        second_task_id = str(second_msg.metadata["_task_id"])
        old_task = loop.ledger.read_task(first_task_id)
        new_task = loop.ledger.read_task(second_task_id)

        assert old_task is not None
        assert old_task["status"] == "completed"
        assert old_task["current_stage"] == "done"
        assert old_task["metadata"].get("recovery_history") in (None, [])

        assert new_task is not None
        runtime_correction = new_task["metadata"]["runtime_correction"]
        assert runtime_correction["kind"] == "continue"
        assert runtime_correction["interrupted_task_count"] == 0
        assert runtime_correction["continued_task_count"] == 1
        assert runtime_correction["continued_task_ids"] == [first_task_id]
        assert runtime_correction["continued_task_stages"] == ["dispatch"]
        assert runtime_correction["delivery_intent"]["delivery_policy"]["mode"] == "final_only"
        assert new_task["resume_context"]["runtime_correction"]["continued_task_ids"] == [first_task_id]
        assert new_task["resume_context"]["runtime_correction"]["continued_task_stages"] == ["dispatch"]
        assert new_task["resume_context"]["runtime_correction"]["delivery_intent"]["delivery_policy"]["preserve_message_identity"] is True
        assert new_task["metadata"]["recovery_history"][-1]["details"]["continued_task_stages"] == ["dispatch"]
        assert new_task["metadata"]["recovery_history"][-1]["details"]["delivery_intent"]["delivery_policy"]["mode"] == "final_only"
        assert new_task["metadata"]["recovery_history"][-1]["action"] == "runtime_correction_continue"


class TestSubagentCancellation:
    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        from lemonclaw.agent.subagent import SubagentManager
        from lemonclaw.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        mgr._running_tasks["sub-1"] = task
        mgr._session_tasks["test:c1"] = {"sub-1"}

        count = await mgr.cancel_by_session("test:c1")
        assert count == 1
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_cancel_by_session_no_tasks(self):
        from lemonclaw.agent.subagent import SubagentManager
        from lemonclaw.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)
        assert await mgr.cancel_by_session("nonexistent") == 0


    @pytest.mark.asyncio
    async def test_stop_event_after_parallel_tools_returns_stopped(self):
        from lemonclaw.agent.loop import AgentLoop
        from lemonclaw.providers.base import LLMResponse, ToolCallRequest

        loop, _bus = _make_loop()
        stop_event = asyncio.Event()
        response = LLMResponse(content=None, tool_calls=[
            ToolCallRequest(id='a', name='exec', arguments={'command': 'echo a'}),
            ToolCallRequest(id='b', name='exec', arguments={'command': 'echo b'}),
        ])
        loop.provider.chat = AsyncMock(return_value=response)

        async def fake_execute(name, params, context=None):
            await asyncio.sleep(0.01)
            stop_event.set()
            return 'ok'

        loop.tools.execute = fake_execute  # type: ignore[assignment]
        final, _tools, _messages, _usage = await loop._run_agent_loop([
            {'role': 'user', 'content': 'test'}
        ], stop_event=stop_event)
        assert final == '⏹ Task stopped.'
