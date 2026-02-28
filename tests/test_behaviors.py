"""Behavioral regression tests for LemonClaw agent.

Based on real failure scenarios from OpenClaw 12,671 issues,
nanobot 309 issues, and LemonClaw production bugs.

Run: pytest tests/test_behaviors.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.providers.base import LLMResponse, ToolCallRequest
from lemonclaw.telemetry.usage import TurnUsage, UsageTracker


# ── 2a. Tool Safety (CVE-2026-25253, shell.py deny_patterns) ──


class TestToolSafety:
    """Dangerous commands must be blocked by ExecTool."""

    @pytest.fixture
    def exec_tool(self):
        return ExecTool(timeout=5)

    @pytest.mark.asyncio
    async def test_rm_rf_blocked(self, exec_tool):
        result = await exec_tool.execute(command="rm -rf /tmp/test")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_dd_blocked(self, exec_tool):
        result = await exec_tool.execute(command="dd if=/dev/zero of=/tmp/x")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_shutdown_blocked(self, exec_tool):
        result = await exec_tool.execute(command="shutdown -h now")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_fork_bomb_blocked(self, exec_tool):
        result = await exec_tool.execute(command=":(){ :|:& };:")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_safe_command_allowed(self, exec_tool):
        result = await exec_tool.execute(command="echo hello")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_python_shutil_allowed(self, exec_tool):
        """skill-installer uses python3 shutil.rmtree instead of rm -rf."""
        result = await exec_tool.execute(
            command="python3 -c \"import shutil; print('ok')\""
        )
        assert "ok" in result

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self):
        tool = ExecTool(timeout=5, restrict_to_workspace=True, working_dir="/tmp")
        result = await tool.execute(command="cat ../../etc/passwd")
        assert "blocked" in result.lower() or "Error" in result


# ── 2b. Session Management (nanobot #1255, #1318) ──


class TestSlashCommands:
    """Slash commands must respond correctly."""

    @pytest.mark.asyncio
    async def test_help_contains_lemonclaw(self, make_agent_loop):
        loop, bus = make_agent_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/help"
        )
        response = await loop._process_message(msg)
        assert response is not None
        assert "LemonClaw" in response.content

    @pytest.mark.asyncio
    async def test_usage_contains_token(self, make_agent_loop):
        loop, bus = make_agent_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/usage"
        )
        response = await loop._process_message(msg)
        assert response is not None
        assert "token" in response.content.lower()

    @pytest.mark.asyncio
    async def test_new_clears_session(self, make_agent_loop):
        loop, bus = make_agent_loop()
        # First, create some history
        msg1 = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="hello"
        )
        await loop._process_message(msg1)
        session = loop.sessions.get_or_create("test:c1")
        assert len(session.messages) > 0

        # /new requires memory consolidation to succeed — mock it
        with patch.object(loop, "_consolidate_memory", new_callable=AsyncMock, return_value=True):
            msg2 = InboundMessage(
                channel="test", sender_id="u1", chat_id="c1", content="/new"
            )
            response = await loop._process_message(msg2)
        assert response is not None
        assert "new session" in response.content.lower() or "started" in response.content.lower()


# ── 2c. Token Tracking (P2-A) ──


class TestTokenTracking:
    def test_turn_usage_accumulates(self):
        tu = TurnUsage()
        tu.record({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        tu.record({"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})
        assert tu.prompt_tokens == 300
        assert tu.completion_tokens == 150
        assert tu.total_tokens == 450
        assert tu.llm_calls == 2

    def test_turn_usage_fallback_when_total_zero(self):
        """Some providers return total_tokens=0."""
        tu = TurnUsage()
        tu.record({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 0})
        assert tu.total_tokens == 150  # fallback: prompt + completion

    def test_usage_tracker_budget_alert(self):
        tracker = UsageTracker(token_budget_per_session=1000)
        tu = TurnUsage()
        tu.record({"prompt_tokens": 400, "completion_tokens": 100, "total_tokens": 500})
        metadata: dict = {}
        alerts = tracker.record_turn("test:c1", tu, metadata)
        assert len(alerts) == 0  # 50% - no alert yet

        tu2 = TurnUsage()
        tu2.record({"prompt_tokens": 400, "completion_tokens": 200, "total_tokens": 600})
        alerts2 = tracker.record_turn("test:c1", tu2, metadata)
        assert len(alerts2) >= 1  # 1100/1000 = 110% - should alert

    def test_usage_tracker_no_division_by_zero(self):
        tracker = UsageTracker(token_budget_per_session=0)
        tu = TurnUsage()
        tu.record({"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        metadata: dict = {}
        # Should not raise
        alerts = tracker.record_turn("test:c1", tu, metadata)
        assert isinstance(alerts, list)


# ── 2d. Repeated Tool Error Detection ──


class TestRepeatedToolErrors:
    """Agent loop should break on repeated identical tool errors."""

    @pytest.mark.asyncio
    async def test_breaks_on_repeated_errors(self, make_agent_loop, echo_provider):
        """LLM keeps calling read_file({}) → should break after 3 failures."""
        # Script: LLM returns read_file({}) tool call every time
        echo_provider.responses = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(
                    id=f"call_{i}", name="read_file", arguments={}
                )],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            for i in range(10)
        ]
        # Add a final text response (won't be reached if break works)
        echo_provider.responses.append(
            LLMResponse(content="done", usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7})
        )

        loop, bus = make_agent_loop(max_iterations=40)
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="test"
        )
        response = await loop._process_message(msg)
        assert response is not None
        # Should have broken early, not reached 40 iterations
        assert "failed repeatedly" in response.content.lower() or "error" in response.content.lower()


# ── 2e. Gateway /api/chat Endpoint ──


class TestChatEndpoint:
    """POST /api/chat should work correctly."""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop)
        client = TestClient(app)

        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert len(data["response"]) > 0

    @pytest.mark.asyncio
    async def test_chat_requires_message(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop)
        client = TestClient(app)

        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_auth_required(self, make_agent_loop):
        from starlette.testclient import TestClient
        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="secret123", agent_loop=loop)
        client = TestClient(app)

        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 401

        resp2 = client.post(
            "/api/chat",
            json={"message": "hello"},
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp2.status_code == 200
