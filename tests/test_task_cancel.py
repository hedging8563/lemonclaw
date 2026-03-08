"""Tests for /stop task cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from lemonclaw.agent.loop import AgentLoop
    from lemonclaw.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("lemonclaw.agent.loop.ContextBuilder"), \
         patch("lemonclaw.agent.loop.SessionManager"), \
         patch("lemonclaw.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


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
