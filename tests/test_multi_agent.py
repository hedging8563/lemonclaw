"""Tests for multi-agent bus and registry (P3 Phase 1)."""

import asyncio

import pytest

from lemonclaw.agent.types import AgentInfo, AgentStatus
from lemonclaw.bus.events import InboundMessage
from lemonclaw.bus.queue import DEFAULT_AGENT_ID, MessageBus


# ── MessageBus routing ────────────────────────────────────────────────────


async def test_default_agent_always_registered():
    bus = MessageBus()
    assert DEFAULT_AGENT_ID in bus.registered_agents


async def test_publish_routes_to_default_when_no_target():
    bus = MessageBus()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
    await bus.publish_inbound(msg)
    received = await asyncio.wait_for(bus.consume_inbound(DEFAULT_AGENT_ID), timeout=1.0)
    assert received.content == "hello"


async def test_publish_routes_to_specific_agent():
    bus = MessageBus()
    bus.register_agent("player-1")
    msg = InboundMessage(
        channel="internal", sender_id="conductor", chat_id="player-1",
        content="do task", target_agent_id="player-1",
    )
    await bus.publish_inbound(msg)

    # Default queue should be empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(bus.consume_inbound(DEFAULT_AGENT_ID), timeout=0.1)

    # Player queue should have the message
    received = await asyncio.wait_for(bus.consume_inbound("player-1"), timeout=1.0)
    assert received.content == "do task"


async def test_unknown_target_falls_back_to_default():
    bus = MessageBus()
    msg = InboundMessage(
        channel="test", sender_id="u1", chat_id="c1",
        content="lost", target_agent_id="nonexistent",
    )
    await bus.publish_inbound(msg)
    received = await asyncio.wait_for(bus.consume_inbound(DEFAULT_AGENT_ID), timeout=1.0)
    assert received.content == "lost"


async def test_unregister_agent():
    bus = MessageBus()
    bus.register_agent("temp")
    assert "temp" in bus.registered_agents
    bus.unregister_agent("temp")
    assert "temp" not in bus.registered_agents


async def test_cannot_unregister_default():
    bus = MessageBus()
    bus.unregister_agent(DEFAULT_AGENT_ID)
    assert DEFAULT_AGENT_ID in bus.registered_agents


async def test_consume_unregistered_agent_raises():
    bus = MessageBus()
    with pytest.raises(ValueError, match="not registered"):
        await bus.consume_inbound("ghost")


# ── AgentRegistry ─────────────────────────────────────────────────────────


async def test_registry_create_and_list(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)

    info = reg.create_agent("writer-1", role="content_writer", model="claude-sonnet")
    assert info.agent_id == "writer-1"
    assert info.role == "content_writer"
    assert info.status == AgentStatus.IDLE
    assert "writer-1" in bus.registered_agents

    agents = reg.list_agents()
    assert len(agents) == 1
    assert agents[0].agent_id == "writer-1"


async def test_registry_duplicate_raises(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    reg.create_agent("a1", role="test")
    with pytest.raises(ValueError, match="already exists"):
        reg.create_agent("a1", role="test")


async def test_registry_retire(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    reg.create_agent("a1", role="test")
    assert reg.retire_agent("a1")
    assert reg.get_agent("a1").status == AgentStatus.RETIRED
    assert "a1" not in bus.registered_agents

    # Retired agents hidden by default
    assert len(reg.list_agents()) == 0
    assert len(reg.list_agents(include_retired=True)) == 1


async def test_registry_persist_and_load(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry

    bus1 = MessageBus()
    reg1 = AgentRegistry(bus1, tmp_path)
    reg1.create_agent("p1", role="player", model="gpt-4")
    reg1.record_task_result("p1", success=True)
    reg1.record_task_result("p1", success=False)

    # Simulate restart: new bus + registry, load from disk
    bus2 = MessageBus()
    reg2 = AgentRegistry(bus2, tmp_path)
    reg2.load()

    info = reg2.get_agent("p1")
    assert info is not None
    assert info.model == "gpt-4"
    assert info.tasks_completed == 1
    assert info.tasks_failed == 1
    assert "p1" in bus2.registered_agents


async def test_registry_task_stats(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    reg.create_agent("a1", role="test")

    reg.record_task_result("a1", success=True)
    reg.record_task_result("a1", success=True)
    reg.record_task_result("a1", success=False)

    info = reg.get_agent("a1")
    assert info.tasks_completed == 2
    assert info.tasks_failed == 1
    assert abs(info.success_rate - 2 / 3) < 0.01


# ── Agent ops tools ───────────────────────────────────────────────────────


async def test_create_agent_tool(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.agent.tools.agent_ops import CreateAgentTool

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    tool = CreateAgentTool(reg)

    result = await tool.execute(agent_id="w1", role="writer")
    assert "created" in result.lower()
    assert reg.get_agent("w1") is not None

    # Duplicate
    result = await tool.execute(agent_id="w1", role="writer")
    assert "error" in result.lower()


async def test_list_agents_tool(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.agent.tools.agent_ops import ListAgentsTool

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    tool = ListAgentsTool(reg)

    result = await tool.execute()
    assert "no agents" in result.lower()

    reg.create_agent("a1", role="coder")
    result = await tool.execute()
    assert "a1" in result
    assert "coder" in result


async def test_send_to_agent_tool(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.agent.tools.agent_ops import SendToAgentTool

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    reg.create_agent("p1", role="player")
    tool = SendToAgentTool(reg, bus)

    result = await tool.execute(agent_id="p1", message="do something")
    assert "sent" in result.lower()

    # Verify message landed in p1's queue
    msg = await asyncio.wait_for(bus.consume_inbound("p1"), timeout=1.0)
    assert msg.content == "do something"
    assert msg.target_agent_id == "p1"


async def test_send_to_nonexistent_agent(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.agent.tools.agent_ops import SendToAgentTool

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    tool = SendToAgentTool(reg, bus)

    result = await tool.execute(agent_id="ghost", message="hello")
    assert "not found" in result.lower()


async def test_get_agent_status_tool(tmp_path):
    from lemonclaw.agent.registry import AgentRegistry
    from lemonclaw.agent.tools.agent_ops import GetAgentStatusTool

    bus = MessageBus()
    reg = AgentRegistry(bus, tmp_path)
    reg.create_agent("a1", role="researcher", model="claude-sonnet")
    tool = GetAgentStatusTool(reg)

    result = await tool.execute(agent_id="a1")
    assert "researcher" in result
    assert "claude-sonnet" in result
    assert "idle" in result

    result = await tool.execute(agent_id="nope")
    assert "not found" in result.lower()


# ── Bus request-response mechanism ────────────────────────────────────────


async def test_bus_request_response():
    bus = MessageBus()
    request_id = "req-001"
    fut = bus.expect_response(request_id)
    assert not fut.done()

    # Simulate agent resolving the response
    assert bus.resolve_response(request_id, "hello from agent")
    assert fut.done()
    assert await fut == "hello from agent"


async def test_bus_resolve_unknown_request():
    bus = MessageBus()
    assert not bus.resolve_response("nonexistent", "data")


async def test_bus_cancel_response():
    bus = MessageBus()
    fut = bus.expect_response("req-002")
    bus.cancel_response("req-002")
    assert fut.cancelled()


async def test_bus_request_response_roundtrip():
    """Simulate Conductor → Bus → Agent → resolve pattern."""
    bus = MessageBus()
    bus.register_agent("player-1")

    request_id = "orch-abc-t1"
    fut = bus.expect_response(request_id)

    # Conductor sends message to player
    msg = InboundMessage(
        channel="internal", sender_id="conductor", chat_id="player-1",
        content="do research", target_agent_id="player-1",
        metadata={"_request_id": request_id},
    )
    await bus.publish_inbound(msg)

    # Agent consumes and processes
    received = await asyncio.wait_for(bus.consume_inbound("player-1"), timeout=1.0)
    assert received.metadata["_request_id"] == request_id

    # Agent resolves
    bus.resolve_response(request_id, "research complete")
    result = await asyncio.wait_for(fut, timeout=1.0)
    assert result == "research complete"
