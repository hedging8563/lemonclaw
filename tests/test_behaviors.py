"""Behavioral regression tests for LemonClaw agent.

Based on real failure scenarios from OpenClaw 12,671 issues,
nanobot 309 issues, and LemonClaw production bugs.

Run: pytest tests/test_behaviors.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.bus.events import InboundMessage
from lemonclaw.config.schema import Config, GitAuthProfileConfig
from lemonclaw.providers.base import LLMResponse, ToolCallRequest
from lemonclaw.telemetry.usage import TurnUsage, UsageTracker

# ── 1. URL shape validation (web.py) ──


class TestWebValidation:
    """web_fetch now only validates URL shape in full-power mode."""

    def test_validate_url_allows_private(self):
        from lemonclaw.agent.tools.web import _validate_url

        valid, err, _ip = _validate_url("http://127.0.0.1:8080/secret")
        assert valid is True
        assert err == ""

    def test_validate_url_allows_metadata_host(self):
        from lemonclaw.agent.tools.web import _validate_url

        valid, err, _ip = _validate_url("http://169.254.169.254/latest/meta-data/")
        assert valid is True
        assert err == ""

    def test_validate_url_allows_public(self):
        from lemonclaw.agent.tools.web import _validate_url

        valid, err, _ip = _validate_url("https://example.com")
        assert valid is True
        assert err == ""

    def test_validate_url_still_rejects_non_http_scheme(self):
        from lemonclaw.agent.tools.web import _validate_url

        valid, err, _ip = _validate_url("file:///etc/passwd")
        assert valid is False
        assert "http/https" in err


@pytest.mark.asyncio
async def test_empty_upstream_reply_does_not_pollute_session_history(make_agent_loop):
    loop, _bus = make_agent_loop()
    loop.provider.chat = AsyncMock(return_value=LLMResponse(content=None, tool_calls=[]))
    loop.tools.get_definitions = MagicMock(return_value=[])

    msg = InboundMessage(channel="webui", sender_id="user1", chat_id="default", content="今天深圳天气")
    result = await loop._process_message(msg)

    assert result is not None
    assert result.content == "处理完成，但没有需要回复的内容。"

    session = loop.sessions.get_or_create(msg.session_key)
    assert [message.get("role") for message in session.messages] == ["user"]
    assert session.messages[0].get("content") == "今天深圳天气"


@pytest.mark.asyncio
async def test_compaction_keeps_current_turn_boundary_for_fallback(make_agent_loop):
    loop, _bus = make_agent_loop()
    loop.provider.chat = AsyncMock(side_effect=[
        LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id='tool-1', name='exec', arguments={'command': 'echo hi'})],
        ),
        LLMResponse(content=None),
    ])
    loop.tools.get_definitions = MagicMock(return_value=[])

    async def fake_execute(name, params, context=None):
        return 'ok'

    async def fake_compact(messages, model, provider):
        return [messages[0], {'role': 'user', 'content': '[Conversation Summary]'}, *messages[-4:]]

    loop.tools.execute = fake_execute  # type: ignore[assignment]
    initial_messages = [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'older question'},
        {'role': 'assistant', 'content': 'older answer'},
        {'role': 'user', 'content': 'prefixed current', '_original_text': 'current question'},
        {'role': 'assistant', 'content': 'current turn note'},
    ]

    with patch('lemonclaw.session.compaction.needs_compaction', return_value=True), \
         patch('lemonclaw.session.compaction.compact', side_effect=fake_compact):
        final, _tools, _messages, _usage = await loop._run_agent_loop(initial_messages)

    assert final == 'current turn note'


# ── 2a. Shell behavior in Full Power mode ──


class TestToolSafety:
    """ExecTool no longer blocks commands via app-layer deny patterns."""

    @pytest.fixture
    def exec_tool(self):
        return ExecTool(timeout=5)

    @pytest.mark.asyncio
    async def test_rm_rf_runs(self, exec_tool):
        result = await exec_tool.execute(command="rm -rf /tmp/test")
        assert result == "(no output)"

    @pytest.mark.asyncio
    async def test_dd_runs(self, exec_tool):
        result = await exec_tool.execute(command="dd if=/dev/zero of=/tmp/x bs=1 count=1")
        assert "records in" in result or "records out" in result or "(no output)" in result

    @pytest.mark.asyncio
    async def test_shutdown_command_is_not_blocked_by_guard(self, exec_tool):
        assert exec_tool._guard_command("shutdown -h now", Path("/tmp")) is None

    @pytest.mark.asyncio
    async def test_fork_bomb_pattern_not_blocked_by_guard(self, exec_tool):
        assert exec_tool._guard_command(":(){ :|:& };:", Path("/tmp")) is None

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
    async def test_relative_paths_allowed_in_full_power_mode(self, tmp_path):
        outer = tmp_path / "outer.txt"
        outer.write_text("hello", encoding="utf-8")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        tool = ExecTool(timeout=5, working_dir=str(workspace))
        result = await tool.execute(command="cat ../outer.txt")
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_rm_rf_extra_spaces_not_blocked(self):
        tool = ExecTool(timeout=5)
        assert tool._guard_command("rm  -rf  /tmp/test", Path("/tmp")) is None

    @pytest.mark.asyncio
    async def test_rm_quoted_args_not_blocked(self):
        tool = ExecTool(timeout=5)
        assert tool._guard_command("rm '-rf' /tmp/test", Path("/tmp")) is None

    @pytest.mark.asyncio
    async def test_rm_long_flags_not_blocked(self):
        tool = ExecTool(timeout=5)
        assert tool._guard_command("rm --recursive --force /tmp/test", Path("/tmp")) is None

    @pytest.mark.asyncio
    async def test_dd_standalone_not_blocked(self):
        tool = ExecTool(timeout=5)
        assert tool._guard_command("dd if=/dev/urandom of=/tmp/x bs=1M count=100", Path("/tmp")) is None

    @pytest.mark.asyncio
    async def test_parent_segments_allowed_in_full_power_mode(self, tmp_path):
        nested = tmp_path / "workspace" / "foo"
        nested.mkdir(parents=True)
        outer = tmp_path / "workspace" / "outer.txt"
        outer.write_text("ok", encoding="utf-8")
        tool = ExecTool(timeout=5, working_dir=str(tmp_path / "workspace"))
        result = await tool.execute(command="cat foo/../outer.txt")
        assert "ok" in result


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
        assert "/export" in response.content
        assert "/recovery" in response.content

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
        session.metadata["current_model"] = "gpt-5.2"
        loop.sessions.save(session)
        assert len(session.messages) > 0

        # /new requires memory consolidation to succeed — mock it
        with patch.object(loop, "_consolidate_memory", new_callable=AsyncMock, return_value=True):
            msg2 = InboundMessage(
                channel="test", sender_id="u1", chat_id="c1", content="/new"
            )
            response = await loop._process_message(msg2)
        assert response is not None
        assert "new session" in response.content.lower() or "started" in response.content.lower()
        refreshed = loop.sessions.get_or_create("test:c1")
        assert refreshed.metadata.get("current_model") is None

    @pytest.mark.asyncio
    async def test_tasks_command_lists_recent_session_tasks(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/tasks")
        loop.ledger.ensure_task(
            task_id="task_1",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="demo",
        )
        loop.ledger.update_task("task_1", status="waiting", current_stage="verify")

        response = await loop._process_message(msg)

        assert response is not None
        assert "task_1" in response.content
        assert "recheck" in response.content

    @pytest.mark.asyncio
    async def test_recovery_command_lists_current_session_recovery_queue(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/recovery manual")
        loop.ledger.ensure_task(
            task_id="task_1",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="demo",
            metadata={"recovery": {"manual_review_required": True, "reason": "operator follow-up"}},
        )
        loop.ledger.update_task("task_1", status="waiting", current_stage="verify")

        loop.ledger.ensure_task(
            task_id="task_2",
            session_key="test:other",
            agent_id="default",
            mode="chat",
            channel="test",
            goal="other",
            metadata={"recovery": {"manual_review_required": True, "reason": "other session"}},
        )
        loop.ledger.update_task("task_2", status="waiting", current_stage="verify")

        response = await loop._process_message(msg)

        assert response is not None
        assert "task_1" in response.content
        assert "task_2" not in response.content
        assert "manual_review" in response.content or "人工处理" in response.content

    @pytest.mark.asyncio
    async def test_resume_command_executes_safe_resume_for_latest_session_task(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/resume")
        loop.ledger.ensure_task(
            task_id="task_resume",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="resume demo",
        )
        loop.ledger.update_task("task_resume", status="waiting", current_stage="verify")
        loop.execute_safe_resume = AsyncMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_resume",
            "recommended_action": "recheck",
            "reason": "task can be safely rechecked through CompletionGate",
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "task_resume" in response.content
        assert "recheck" in response.content
        loop.execute_safe_resume.assert_awaited_once_with("task_resume", source="chat_command_resume")

    @pytest.mark.asyncio
    async def test_resume_command_explains_unsafe_candidate(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/resume task_manual")
        loop.ledger.ensure_task(
            task_id="task_manual",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="manual demo",
        )
        loop.ledger.build_resume_candidate = MagicMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_manual",
            "recommended_action": "manual_resume",
            "safe_to_execute": False,
            "reason": "manual intervention required",
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "task_manual" in response.content
        assert "manual_resume" in response.content

    @pytest.mark.asyncio
    async def test_retry_outbox_command_executes_retry_for_safe_candidate(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/retry-outbox")
        loop.ledger.ensure_task(
            task_id="task_outbox",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="outbox demo",
            status="waiting",
            current_stage="waiting_outbox",
        )
        loop.ledger.build_resume_candidate = MagicMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_outbox",
            "recommended_action": "retry_outbox",
            "safe_to_execute": True,
            "reason": "1 failed outbox event(s) can be retried safely",
        })
        loop.execute_safe_resume = AsyncMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_outbox",
            "recommended_action": "retry_outbox",
            "reason": "1 failed outbox event(s) can be retried safely",
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "task_outbox" in response.content
        loop.execute_safe_resume.assert_awaited_once_with("task_outbox", source="chat_command_retry_outbox")

    @pytest.mark.asyncio
    async def test_recheck_command_executes_recheck_for_safe_candidate(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/recheck")
        loop.ledger.ensure_task(
            task_id="task_recheck",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="recheck demo",
            status="waiting",
            current_stage="verify",
        )
        loop.ledger.build_resume_candidate = MagicMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_recheck",
            "recommended_action": "recheck",
            "safe_to_execute": True,
            "reason": "task can be safely rechecked through CompletionGate",
        })
        loop.execute_safe_resume = AsyncMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_recheck",
            "recommended_action": "recheck",
            "reason": "task can be safely rechecked through CompletionGate",
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "task_recheck" in response.content
        loop.execute_safe_resume.assert_awaited_once_with("task_recheck", source="chat_command_recheck")

    @pytest.mark.asyncio
    async def test_abandon_command_abandons_latest_active_outbox_event(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/abandon")
        loop.ledger.ensure_task(
            task_id="task_abandon",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="abandon demo",
            status="waiting",
            current_stage="waiting_outbox",
        )
        step = loop.ledger.start_step("task_abandon", step_type="tool_call", name="notify", replayable=False)
        loop.ledger.finish_step(step, status="waiting_outbox")
        event = loop.ledger.enqueue_outbox(
            task_id="task_abandon",
            step_id=step.step_id,
            effect_type="outbound_message",
            target="telegram:123",
            payload={"content": "hello"},
        )

        response = await loop._process_message(msg)

        assert response is not None
        assert event["event_id"] in response.content
        updated = loop.ledger.read_outbox_event(event["event_id"])
        assert updated is not None
        assert updated["status"] == "abandoned"

    @pytest.mark.asyncio
    async def test_bundle_command_summarizes_export_view(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/bundle")
        loop.ledger.ensure_task(
            task_id="task_bundle",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="bundle demo",
            status="waiting",
            current_stage="verify",
        )
        loop.ledger.build_resume_candidate = MagicMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_bundle",
            "recommended_action": "recheck",
            "safe_to_execute": True,
            "reason": "task can be safely rechecked through CompletionGate",
            "failed_outbox_count": 1,
        })
        loop.ledger.build_task_export_view = MagicMock(return_value={  # type: ignore[method-assign]
            "summary": {
                "display_state": {"key": "resume_requested"},
                "verification": {"status": "recorded", "evidence_count": 2},
                "retrieval": {"strategy": "hybrid", "card_count": 1, "rule_count": 2, "knowledge_count": 3},
                "outbox_active_count": 1,
                "outbox_terminal_count": 0,
            },
            "outbox_events": [{"event_id": "ob_1"}],
            "conductor": {"swarm_template_id": "template-a", "subtask_count": 4, "accepted_count": 2, "failed_count": 1},
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "Bundle for `task_bundle`" in response.content
        assert "verification=recorded" in response.content
        assert "template-a" in response.content
        assert "total=1" in response.content

    @pytest.mark.asyncio
    async def test_export_command_renders_full_export_artifact(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/export json")
        loop.ledger.ensure_task(
            task_id="task_export",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="export demo",
            status="waiting",
            current_stage="verify",
        )
        loop.ledger.build_task_export_view = MagicMock(return_value={  # type: ignore[method-assign]
            "task": {"task_id": "task_export", "goal": "export demo", "status": "waiting", "current_stage": "verify"},
            "summary": {},
            "candidate": {"recommended_action": "recheck", "safe_to_execute": True},
            "postmortem": {"outbox": {"lifecycle": {"terminal_count": 0}}},
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "Rendered `export` for `task_export` as `json`." in response.content
        assert '"task_id": "task_export"' in response.content
        assert "```json" in response.content

    @pytest.mark.asyncio
    async def test_bundle_command_can_render_full_bundle_artifact(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/bundle md")
        loop.ledger.ensure_task(
            task_id="task_bundle_full",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="bundle artifact demo",
            status="waiting",
            current_stage="verify",
        )
        loop.ledger.build_task_export_view = MagicMock(return_value={  # type: ignore[method-assign]
            "task": {"task_id": "task_bundle_full", "goal": "bundle artifact demo", "status": "waiting", "current_stage": "verify"},
            "summary": {},
            "candidate": {"recommended_action": "recheck", "safe_to_execute": True},
            "conductor": {},
        })
        loop.ledger.build_task_postmortem_view = MagicMock(return_value={  # type: ignore[method-assign]
            "task": {"task_id": "task_bundle_full", "goal": "bundle artifact demo", "status": "waiting", "current_stage": "verify"},
            "summary": {},
            "outbox": {"events": [], "lifecycle": {"active_count": 0, "terminal_count": 0}},
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "# Task Bundle: task_bundle_full" in response.content
        assert "## Postmortem" in response.content

    @pytest.mark.asyncio
    async def test_postmortem_command_summarizes_failure_state(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/postmortem")
        loop.ledger.ensure_task(
            task_id="task_pm",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="pm demo",
            status="failed",
            current_stage="execute",
        )
        loop.ledger.build_resume_candidate = MagicMock(return_value={  # type: ignore[method-assign]
            "task_id": "task_pm",
            "recommended_action": "manual_resume",
            "safe_to_execute": False,
            "reason": "manual intervention required",
            "failed_outbox_count": 1,
        })
        loop.ledger.build_task_postmortem_view = MagicMock(return_value={  # type: ignore[method-assign]
            "summary": {
                "step_count": 3,
                "display_state": {"key": "manual_resume"},
                "recovery": {"source": "watchdog_soft_recovery", "action": "manual_review", "reason": "manual intervention required"},
            },
            "outbox": {"lifecycle": {"active_count": 0, "terminal_count": 1}},
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "Postmortem for `task_pm`" in response.content
        assert "watchdog_soft_recovery" in response.content
        assert "failed=1" in response.content

    @pytest.mark.asyncio
    async def test_postmortem_command_can_render_full_postmortem_artifact(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/postmortem json")
        loop.ledger.ensure_task(
            task_id="task_pm_full",
            session_key=msg.session_key,
            agent_id="default",
            mode="chat",
            channel="test",
            goal="pm artifact demo",
            status="failed",
            current_stage="execute",
        )
        loop.ledger.build_task_postmortem_view = MagicMock(return_value={  # type: ignore[method-assign]
            "task": {"task_id": "task_pm_full", "goal": "pm artifact demo", "status": "failed", "current_stage": "execute"},
            "summary": {"recovery": {"source": "watchdog_soft_recovery"}},
            "outbox": {"events": [], "lifecycle": {"active_count": 0, "terminal_count": 1}},
        })

        response = await loop._process_message(msg)

        assert response is not None
        assert "Rendered `postmortem` for `task_pm_full` as `json`." in response.content
        assert '"task_id": "task_pm_full"' in response.content
        assert "```json" in response.content

    @pytest.mark.asyncio
    async def test_runtime_command_summarizes_inventory_and_mcp(self, make_agent_loop, monkeypatch):
        loop, _bus = make_agent_loop()
        loop._mcp_connected = True
        loop._mcp_servers = {"Notion": {"command": "npx"}, "Remote": {"url": "https://example.com/mcp"}}
        monkeypatch.setattr(
            "lemonclaw.gateway.webui.settings._derive_runtime_inventory",
            lambda: {
                "persistent_prefixes": [
                    {"path": "/home/lemonclaw", "mounted": True, "fs_type": "overlay", "source": "/mnt/persist"},
                    {"path": "/tmp", "mounted": False, "fs_type": None, "source": None},
                ],
                "binary_inventory": {
                    "browser": {"command": "agent-browser", "installed": True, "binary": "/usr/bin/agent-browser"},
                    "kubectl": {"command": "kubectl", "installed": False, "binary": None},
                },
            },
        )

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/runtime")
        )

        assert response is not None
        assert "mounted=1/2" in response.content
        assert "Notion, Remote" in response.content
        assert "registered_tools=0" in response.content

    @pytest.mark.asyncio
    async def test_runtime_command_can_show_mcp_detail(self, make_agent_loop):
        from lemonclaw.agent.tools.base import Tool

        class _DummyMCPTool(Tool):
            @property
            def name(self) -> str:
                return "mcp_Notion_API-post-search"

            @property
            def description(self) -> str:
                return "dummy"

            @property
            def parameters(self) -> dict:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return "ok"

        loop, _bus = make_agent_loop()
        loop._mcp_connected = False
        loop._mcp_servers = {"Notion": {"command": "npx"}}
        loop.tools.register(_DummyMCPTool())

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/runtime mcp")
        )

        assert response is not None
        assert "Notion" in response.content
        assert "mcp_Notion_API-post-search" in response.content

    @pytest.mark.asyncio
    async def test_runtime_command_can_show_health_detail(self, make_agent_loop):
        from lemonclaw.gateway.runtime_state import mark_restart_requested

        loop, _bus = make_agent_loop()
        loop.config_path = loop.workspace / "config.json"
        loop.config_path.write_text("{}", encoding="utf-8")
        loop.watchdog = MagicMock()
        loop.watchdog.snapshot.return_value = {
            "running": True,
            "state": {
                "recent_error_count": 2,
                "total_soft_recoveries": 3,
                "total_hard_restarts": 1,
            },
            "task_stuck": {"count": 1, "task_ids": ["task_1"]},
            "channels": {
                "telegram": {"enabled": True, "available": True, "running": True, "error": ""},
                "wecom": {"enabled": True, "available": False, "running": False, "error": "missing dependency"},
            },
        }
        mark_restart_requested(
            loop.config_path,
            restart_fields=["tools.mcp_servers"],
            runtime_errors=[],
        )

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/runtime health")
        )

        assert response is not None
        assert "watchdog=yes" in response.content
        assert "stale_tasks=1" in response.content
        assert "telegram" in response.content
        assert "wecom" in response.content
        assert "tools.mcp_servers" in response.content

    @pytest.mark.asyncio
    async def test_runtime_command_can_show_recovery_pack(self, make_agent_loop, monkeypatch):
        from lemonclaw.gateway.runtime_state import mark_restart_requested

        loop, _bus = make_agent_loop()
        loop.config_path = loop.workspace / "config.json"
        loop.config_path.write_text(json.dumps({
            "channels": {
                "autoPairing": True,
                "telegram": {"enabled": True},
            }
        }), encoding="utf-8")
        loop.watchdog = MagicMock()
        loop.watchdog.snapshot.return_value = {
            "running": True,
            "state": {
                "recent_error_count": 1,
                "total_soft_recoveries": 2,
                "total_hard_restarts": 0,
            },
            "task_stuck": {"count": 0, "task_ids": []},
            "channels": {
                "telegram": {"enabled": True, "available": True, "running": True, "error": ""},
            },
        }
        mark_restart_requested(
            loop.config_path,
            restart_fields=["tools.mcp_servers"],
            runtime_errors=[],
        )
        loop.ledger.ensure_task(
            task_id="task_recovery",
            session_key="test:c1",
            agent_id="default",
            mode="chat",
            channel="test",
            goal="recovery demo",
            status="waiting",
            current_stage="verify",
        )
        pairing_dir = loop.workspace / "pairing"
        pairing_dir.mkdir(parents=True, exist_ok=True)
        (pairing_dir / "telegram.json").write_text(json.dumps({
            "owner": "1234567890|alice",
            "owner_notify_target": "1234567890",
            "approved": ["1234567890|alice"],
            "pending": {"user-2": {"display_name": "User 2", "notify_target": "user-2"}},
        }), encoding="utf-8")
        monkeypatch.setenv("HOME", str(loop.workspace))

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/runtime recovery")
        )

        assert response is not None
        assert "Runtime recovery pack" in response.content
        assert "task_recovery" in response.content
        assert "Pairing telegram" in response.content
        assert "tools.mcp_servers" in response.content

    @pytest.mark.asyncio
    async def test_agent_loop_resolves_lemondata_runtime_context_off_thread(self, make_agent_loop, monkeypatch):
        loop, _bus = make_agent_loop()
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def _fake_to_thread(fn, *args, **kwargs):
            calls.append((args, kwargs))
            return fn(*args, **kwargs)

        monkeypatch.setattr(
            "lemonclaw.agent.loop.asyncio.to_thread",
            _fake_to_thread,
        )
        monkeypatch.setattr(
            "lemonclaw.agent.loop.build_lemondata_runtime_block",
            lambda current_message, media=None: "[LemonData Live Capability]\n- focus_model=seedance-2.0",
        )

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="用 seedance-2.0 做图生视频")
        )

        assert response is not None
        assert calls
        assert calls[0][0][0] == "用 seedance-2.0 做图生视频"

    @pytest.mark.asyncio
    async def test_channel_command_shows_channel_status(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        loop.channel_manager = MagicMock()
        loop.channel_manager.get_channel_status.return_value = {
            "telegram": {
                "configured_enabled": True,
                "available": True,
                "running": True,
                "error": "",
            },
            "wecom": {
                "configured_enabled": True,
                "available": False,
                "running": False,
                "error": "missing dependency",
            },
        }

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/channel status")
        )

        assert response is not None
        assert "Configured channel status" in response.content
        assert "telegram" in response.content
        assert "wecom" in response.content

    @pytest.mark.asyncio
    async def test_channel_restart_command_restarts_channel(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        loop.channel_manager = MagicMock()
        loop.channel_manager.restart_channel = AsyncMock(return_value={
            "channel": "telegram",
            "running": True,
            "last_restart_result": "running",
        })

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/channel restart telegram")
        )

        assert response is not None
        assert "telegram" in response.content
        loop.channel_manager.restart_channel.assert_awaited_once_with(
            "telegram",
            reason="chat command restart",
            source="chat_command_restart",
        )

    @pytest.mark.asyncio
    async def test_channel_repair_whatsapp_uses_bridge_helper(self, make_agent_loop, monkeypatch):
        from lemonclaw.config.loader import save_config
        from lemonclaw.config.schema import Config

        loop, _bus = make_agent_loop()
        loop.config_path = loop.workspace / "config.json"
        cfg = Config()
        cfg.channels.whatsapp.enabled = True
        save_config(cfg, loop.config_path)
        monkeypatch.setattr(
            "lemonclaw.channels.whatsapp_bridge_runtime.restart_whatsapp_pairing",
            lambda config, wait_timeout=20.0: {"status": "qr", "running": True, "account": None},
        )

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/channel repair whatsapp")
        )

        assert response is not None
        assert "whatsapp" in response.content.lower()
        assert "status=qr" in response.content.lower()

    @pytest.mark.asyncio
    async def test_channel_repair_weixin_uses_bridge_helper(self, make_agent_loop, monkeypatch):
        from lemonclaw.config.loader import save_config
        from lemonclaw.config.schema import Config

        loop, _bus = make_agent_loop()
        loop.config_path = loop.workspace / "config.json"
        cfg = Config()
        cfg.channels.weixin.enabled = True
        save_config(cfg, loop.config_path)

        ensured: list[str] = []

        class _Manager:
            bus = _bus
            trigger_runtime = None

            def get_channel(self, name: str):
                return None

            async def ensure_channel(self, name: str, channel):
                ensured.append(name)
                return channel

        loop.channel_manager = _Manager()
        monkeypatch.setattr(
            "lemonclaw.channels.weixin_bridge_runtime.get_weixin_pairing_state",
            lambda config, start_if_needed=False, wait_timeout=5.0, **kwargs: {
                "status": "connected",
                "running": True,
                "accounts": [{"accountId": "wx-1"}],
            },
        )

        response = await loop._process_message(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/channel repair weixin")
        )

        assert response is not None
        assert "weixin" in response.content.lower()
        assert "status=connected" in response.content.lower()
        assert ensured == ["weixin"]

    @pytest.mark.asyncio
    async def test_process_message_records_retrieval_observability(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        loop.context.resolve_retrieval_context = AsyncMock(return_value=(
            "## Relevant Memory\n\n### tech\nPython 3.13",
            "## Experience Rules\n\n**python 部署**: 需要 venv → 先创建 venv",
            {
                "strategy": "hybrid",
                "latency_ms": 12,
                "fallback_count": 0,
                "fallbacks": [],
                "card_count": 1,
                "rule_count": 1,
                "hit_sources": ["hybrid"],
                "card_sources": {"tech": "hybrid"},
                "rule_sources": {"## Rule #1": "hybrid"},
            },
        ))
        loop.ledger.ensure_task(
            task_id="task_1",
            session_key="test:c1",
            agent_id="default",
            mode="chat",
            channel="test",
            goal="hello",
        )

        msg = InboundMessage(
            channel="test",
            sender_id="u1",
            chat_id="c1",
            content="hello",
            metadata={"_task_id": "task_1", "_mode": "chat", "_agent_id": "default"},
        )
        response = await loop._process_message(msg)

        assert response is not None
        task = loop.ledger.read_task("task_1")
        assert task is not None
        assert task["metadata"]["retrieval"]["strategy"] == "hybrid"
        assert task["metadata"]["retrieval"]["latency_ms"] == 12


# ── 2c. Token Tracking (P2-A) ──


class TestAPIKeySanitization:
    """API keys must not leak into error messages or logs."""

    def test_sanitize_bearer_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Request failed: Bearer sk-abc123def456ghi789jkl012mno345pqr")
        result = _sanitize_error(err)
        assert "sk-abc123" not in result
        assert "[REDACTED]" in result

    def test_sanitize_api_key_pattern(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Invalid key: key-abcdefghijklmnop1234")
        result = _sanitize_error(err)
        assert "key-abcdefgh" not in result
        assert "[REDACTED]" in result

    def test_sanitize_hex_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Token c09b22eabe503204bc8de0fac10875f7ee54ea5123bf19c29533b51c6359b6e5 expired")
        result = _sanitize_error(err)
        assert "c09b22ea" not in result
        assert "[REDACTED]" in result

    def test_safe_message_unchanged(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception("Connection timeout after 30s")
        result = _sanitize_error(err)
        assert result == "Connection timeout after 30s"

    def test_sanitize_slack_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception('bot token xoxb-1234567890-secret-value leaked')
        result = _sanitize_error(err)
        assert 'xoxb-1234' not in result
        assert '[REDACTED]' in result

    def test_sanitize_jwt_token(self):
        from lemonclaw.providers.litellm_provider import _sanitize_error
        err = Exception('Authorization: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def failed')
        result = _sanitize_error(err)
        assert 'eyJhbGci' not in result
        assert '[REDACTED]' in result


# ── 2c-orig. Token Tracking (P2-A) ──


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
    async def test_empty_write_file_args_fail_fast_with_exec_hint(self, make_agent_loop, echo_provider):
        echo_provider.responses = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="call_0", name="write_file", arguments={})],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            ),
            LLMResponse(content="done", usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
        ]

        loop, _bus = make_agent_loop(max_iterations=10)
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="test")

        response = await loop._process_message(msg)

        assert response is not None
        assert "write_file" in response.content
        assert "exec" in response.content.lower()
        assert echo_provider._call_count == 1

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
        assert "required arguments" in response.content.lower() or "provide complete parameters" in response.content.lower()




    @pytest.mark.asyncio
    async def test_parallel_success_does_not_clear_other_tool_error_budget(self, make_agent_loop, echo_provider):
        from lemonclaw.providers.base import LLMResponse, ToolCallRequest

        call = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(id='err1', name='read_file', arguments={}),
                ToolCallRequest(id='ok1', name='exec', arguments={'command': 'echo ok'}),
            ],
            usage={'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        )
        echo_provider.responses = [call, call, call]
        loop, _bus = make_agent_loop(max_iterations=10)

        async def fake_execute(name, params, context=None):
            if name == 'read_file':
                return "Error: Invalid parameters for tool 'read_file': path is required"
            return 'ok'
        loop.tools.execute = fake_execute  # type: ignore[assignment]

        msg = InboundMessage(channel='test', sender_id='u1', chat_id='c1', content='test')
        response = await loop._process_message(msg)
        assert response is not None
        assert "required arguments" in response.content.lower() or "provide complete parameters" in response.content.lower()

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


# ── 5. WeCom Channel (crypto, signature, webhook) ──


class TestWeComCrypto:
    """WeCom AES encryption/decryption and signature verification."""

    CORP_ID = "wx1234567890abcdef"
    # 43-char base64 key (decodes to 32 bytes)
    ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"

    def test_encrypt_decrypt_roundtrip(self):
        from lemonclaw.channels.wecom import WeComCrypto

        crypto = WeComCrypto(self.ENCODING_AES_KEY, self.CORP_ID)
        original = "<xml><Content>hello world</Content></xml>"
        encrypted = crypto.encrypt(original)
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_wrong_corp_id_fails(self):
        from lemonclaw.channels.wecom import WeComCrypto

        crypto = WeComCrypto(self.ENCODING_AES_KEY, self.CORP_ID)
        wrong_crypto = WeComCrypto(self.ENCODING_AES_KEY, "wx_wrong_corp")

        encrypted = wrong_crypto.encrypt("test message")
        with pytest.raises(ValueError, match="corp_id mismatch"):
            crypto.decrypt(encrypted)

    def test_decrypt_invalid_padding_fails(self):
        """Tampered ciphertext should raise ValueError on padding validation."""
        import base64

        from lemonclaw.channels.wecom import WeComCrypto

        crypto = WeComCrypto(self.ENCODING_AES_KEY, self.CORP_ID)
        encrypted = crypto.encrypt("test message")
        # Tamper with the last block (corrupts padding)
        raw = base64.b64decode(encrypted)
        tampered = raw[:-1] + bytes([(raw[-1] + 1) % 256])
        tampered_b64 = base64.b64encode(tampered).decode()
        with pytest.raises(ValueError):
            crypto.decrypt(tampered_b64)

    def test_verify_signature(self):
        from lemonclaw.channels.wecom import verify_signature

        token = "test_token"
        timestamp = "1234567890"
        nonce = "abc123"
        encrypt = "encrypted_data"

        sig = verify_signature(token, timestamp, nonce, encrypt)
        assert len(sig) == 40  # SHA1 hex digest
        # Same inputs → same output
        assert sig == verify_signature(token, timestamp, nonce, encrypt)
        # Different input → different output
        assert sig != verify_signature(token, timestamp, nonce, "other_data")

    def test_signature_timing_safe(self):
        """Signature comparison must use hmac.compare_digest (timing-safe)."""
        import hmac as hmac_mod

        from lemonclaw.channels.wecom import verify_signature
        sig = verify_signature("tok", "123", "abc", "enc")
        # Verify hmac.compare_digest works with the output
        assert hmac_mod.compare_digest(sig, sig) is True
        assert hmac_mod.compare_digest(sig, "wrong" * 8) is False


class TestWeComXML:
    """WeCom XML parsing and building."""

    def test_parse_xml(self):
        from lemonclaw.channels.wecom import parse_xml

        xml = (
            "<xml>"
            "<ToUserName><![CDATA[corp_id]]></ToUserName>"
            "<FromUserName><![CDATA[user_id]]></FromUserName>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[hello]]></Content>"
            "<MsgId>12345</MsgId>"
            "</xml>"
        )
        result = parse_xml(xml)
        assert result["ToUserName"] == "corp_id"
        assert result["FromUserName"] == "user_id"
        assert result["MsgType"] == "text"
        assert result["Content"] == "hello"
        assert result["MsgId"] == "12345"

    def test_build_reply_xml(self):
        from lemonclaw.channels.wecom import build_reply_xml

        xml = build_reply_xml("enc_data", "sig123", "1234567890", "nonce_abc")
        assert "<Encrypt><![CDATA[enc_data]]></Encrypt>" in xml
        assert "<MsgSignature><![CDATA[sig123]]></MsgSignature>" in xml
        assert "<TimeStamp>1234567890</TimeStamp>" in xml


class TestWeComWebhook:
    """WeCom webhook endpoint integration tests."""

    @pytest.mark.asyncio
    async def test_webhook_get_returns_404_without_channel(self):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        app = create_app(auth_token=None, channel_manager=None)
        client = TestClient(app)
        resp = client.get("/webhook/wecom?msg_signature=x&timestamp=1&nonce=a&echostr=b")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_webhook_post_returns_404_without_channel(self):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        app = create_app(auth_token=None, channel_manager=None)
        client = TestClient(app)
        resp = client.post("/webhook/wecom?msg_signature=x&timestamp=1&nonce=a", content="<xml></xml>")
        assert resp.status_code == 404


# ── 6a. WebUI Auth (HMAC cookie) ──


class TestWebUIAuth:
    """HMAC cookie authentication for WebUI."""

    def test_verify_token_correct(self):
        from lemonclaw.gateway.webui.auth import verify_token
        assert verify_token("secret123", "secret123") is True

    def test_verify_token_wrong(self):
        from lemonclaw.gateway.webui.auth import verify_token
        assert verify_token("wrong", "secret123") is False

    def test_cookie_roundtrip(self):
        from lemonclaw.gateway.webui.auth import create_session_cookie, verify_session_cookie
        cookie = create_session_cookie("mytoken")
        valid, refreshed = verify_session_cookie(cookie, "mytoken")
        assert valid is True
        assert refreshed is not None

    def test_cookie_wrong_token(self):
        from lemonclaw.gateway.webui.auth import create_session_cookie, verify_session_cookie
        cookie = create_session_cookie("mytoken")
        valid, refreshed = verify_session_cookie(cookie, "othertoken")
        assert valid is False
        assert refreshed is None

    def test_cookie_expired_absolute(self):
        import time as time_mod
        from unittest.mock import patch as mock_patch

        from lemonclaw.gateway.webui.auth import (
            ABSOLUTE_TIMEOUT,
            create_session_cookie,
            verify_session_cookie,
        )

        cookie = create_session_cookie("tok")
        # Advance time past absolute timeout
        future = time_mod.time() + ABSOLUTE_TIMEOUT + 60
        with mock_patch("lemonclaw.gateway.webui.auth.time.time", return_value=future):
            valid, _ = verify_session_cookie(cookie, "tok")
        assert valid is False

    def test_cookie_expired_idle(self):
        import time as time_mod
        from unittest.mock import patch as mock_patch

        from lemonclaw.gateway.webui.auth import (
            IDLE_TIMEOUT,
            create_session_cookie,
            verify_session_cookie,
        )

        cookie = create_session_cookie("tok")
        # Advance time past idle timeout but within absolute
        future = time_mod.time() + IDLE_TIMEOUT + 60
        with mock_patch("lemonclaw.gateway.webui.auth.time.time", return_value=future):
            valid, _ = verify_session_cookie(cookie, "tok")
        assert valid is False


    def test_cookie_rejects_future_created_timestamp(self):
        import base64

        from lemonclaw.gateway.webui.auth import _compute_hmac, verify_session_cookie
        future_created = '9999999999'
        last = '9999999999'
        nonce = 'abc123'
        payload = f"{future_created}:{last}:{nonce}"
        cookie = base64.urlsafe_b64encode(f"{payload}:{_compute_hmac(payload, 'tok')}".encode()).decode()
        valid, _ = verify_session_cookie(cookie, 'tok')
        assert valid is False

    def test_cookie_rejects_last_before_created(self):
        import base64

        from lemonclaw.gateway.webui.auth import _compute_hmac, verify_session_cookie
        payload = '200:100:abc123'
        cookie = base64.urlsafe_b64encode(f"{payload}:{_compute_hmac(payload, 'tok')}".encode()).decode()
        valid, _ = verify_session_cookie(cookie, 'tok')
        assert valid is False


class TestLegacyToolCallCompatibility:
    def test_serialize_ui_message_formats_old_tool_calls(self):
        from lemonclaw.gateway.webui.message_schema import serialize_ui_message

        msg = serialize_ui_message({
            'role': 'assistant',
            'content': '',
            'tool_calls': [
                {
                    'function': {
                        'name': 'read_file',
                        'arguments': '{"path":"/tmp/demo.txt"}',
                    }
                }
            ],
        })
        tool_block = next(block for block in msg['blocks'] if block['type'] == 'tool')
        assert 'read_file' in tool_block['detail']
        assert '/tmp/demo.txt' in tool_block['detail']

class TestNativeBlockSchemaPersistence:
    @pytest.mark.asyncio
    async def test_slash_command_persists_system_notice_block(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/usage")
        resp = await loop._process_message(msg)
        assert resp is not None
        session = loop.sessions.get_or_create("test:c1")
        assistant = next(m for m in session.messages if m.get("role") == "assistant")
        assert any(block["type"] == "system_notice" for block in assistant["blocks"])
        assert any(block["type"] == "markdown" for block in assistant["blocks"])

    @pytest.mark.asyncio
    async def test_kb_command_searches_ingested_knowledge(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(loop.workspace)
        doc = store.create_document(
            source_type="manual",
            source="manual://release-notes",
            title="Release Notes",
            content="Trigger history can explain delivery spikes after rollout.",
        )
        store.ingest_document(doc["doc_id"])

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/kb trigger history")
        resp = await loop._process_message(msg)

        assert resp is not None
        assert "Release Notes" in resp.content
        assert "trigger history" in resp.content.lower()

    @pytest.mark.asyncio
    async def test_kb_add_command_creates_and_ingests_manual_knowledge(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        from lemonclaw.knowledge import KnowledgeStore

        msg = InboundMessage(
            channel="test",
            sender_id="u1",
            chat_id="c1",
            content="/kb add Runbook :: Retry the outbox queue before manual recovery.",
        )
        resp = await loop._process_message(msg)

        assert resp is not None
        assert "Runbook" in resp.content
        assert "ingested" in resp.content.lower()

        store = KnowledgeStore(loop.workspace)
        docs = store.list_documents()
        assert docs
        assert docs[0]["title"] == "Runbook"
        assert docs[0]["status"] == "ingested"

    @pytest.mark.asyncio
    async def test_kb_list_command_lists_documents(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(loop.workspace)
        first = store.create_document(
            source_type="manual",
            source="manual://one",
            title="Ops Playbook",
            content="Watch trigger spikes after a rollout.",
        )
        second = store.create_document(
            source_type="manual",
            source="manual://two",
            title="Escalation Guide",
            content="Escalate after recovery and postmortem collection.",
        )
        store.ingest_document(first["doc_id"])
        store.ingest_document(second["doc_id"])

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/kb list 2")
        resp = await loop._process_message(msg)

        assert resp is not None
        assert "Knowledge documents" in resp.content
        assert "Escalation Guide" in resp.content
        assert "Ops Playbook" in resp.content
        assert "status=ingested" in resp.content

    @pytest.mark.asyncio
    async def test_kb_pin_and_unpin_commands_toggle_document_priority(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(loop.workspace)
        doc = store.create_document(
            source_type="manual",
            source="manual://pin-me",
            title="Pinned Candidate",
            content="Keep this runbook at the top.",
        )

        pin_msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content=f"/kb pin {doc['doc_id']}")
        pin_resp = await loop._process_message(pin_msg)
        assert pin_resp is not None
        assert "Pinned Candidate" in pin_resp.content

        pinned = store.read_document(doc["doc_id"])
        assert pinned is not None
        assert pinned["pinned"] is True

        list_resp = await loop._process_message(InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/kb list 1"))
        assert list_resp is not None
        assert "[PIN]" in list_resp.content

        unpin_msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content=f"/kb unpin {doc['doc_id']}")
        unpin_resp = await loop._process_message(unpin_msg)
        assert unpin_resp is not None
        assert "Pinned Candidate" in unpin_resp.content

        unpinned = store.read_document(doc["doc_id"])
        assert unpinned is not None
        assert unpinned["pinned"] is False

    @pytest.mark.asyncio
    async def test_kb_show_command_displays_document_detail(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(loop.workspace)
        doc = store.create_document(
            source_type="manual",
            source="manual://show-me",
            title="Show Me",
            note="Useful note",
            content="This document explains the recovery checklist in detail.",
        )
        store.ingest_document(doc["doc_id"])

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content=f"/kb show {doc['doc_id']}")
        resp = await loop._process_message(msg)

        assert resp is not None
        assert "Knowledge document: Show Me" in resp.content
        assert f"id={doc['doc_id']}" in resp.content
        assert "chunk:" in resp.content
        assert "fact:" in resp.content

    @pytest.mark.asyncio
    async def test_kb_retry_failed_reingests_error_documents(self, make_agent_loop):
        loop, _bus = make_agent_loop()
        from lemonclaw.knowledge import KnowledgeStore

        store = KnowledgeStore(loop.workspace)
        doc = store.create_document(
            source_type="manual",
            source="manual://retry-me",
            title="Retry Me",
            content="Initial content",
        )
        original_loader = store._load_document_content

        def _fail(_document):
            raise RuntimeError("boom")

        store._load_document_content = _fail  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="boom"):
            store.ingest_document(doc["doc_id"])
        store._load_document_content = original_loader  # type: ignore[assignment]

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/kb retry-failed 5")
        resp = await loop._process_message(msg)

        assert resp is not None
        assert "updated=1" in resp.content
        refreshed = store.read_document(doc["doc_id"])
        assert refreshed is not None
        assert refreshed["status"] == "ingested"

    @pytest.mark.asyncio
    async def test_tool_only_message_persists_tool_block(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from lemonclaw.agent.loop import AgentLoop
        from lemonclaw.bus.queue import MessageBus
        from lemonclaw.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)

        tool_call = ToolCallRequest(id="call1", name="message", arguments={"content": "Hello", "channel": "email", "chat_id": "a@b.com"})
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        await loop.process_direct("send mail", session_key="webui:test-tool", channel="webui", chat_id="webui")
        session = loop.sessions.get_or_create("webui:test-tool")
        tool_only = next(m for m in session.messages if m.get("role") == "assistant" and any(b["type"] == "tool" for b in m.get("blocks", [])))
        assert any(block["type"] == "tool" for block in tool_only["blocks"])


# ── 6b. WebUI Routes ──


class TestWebUIMediaAndAttachments:
    """Media endpoint and outbound media[] persistence tests."""

    @pytest.mark.asyncio
    async def test_media_endpoint_serves_session_attachment_file(self, make_agent_loop, tmp_path):
        from pathlib import Path

        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app
        from lemonclaw.gateway.webui.message_schema import serialize_ui_message

        loop, bus = make_agent_loop()
        media_file = Path(loop.workspace) / 'preview.png'
        media_file.write_bytes(b'fakepng')
        session = loop.sessions.get_or_create('webui:test-media')
        session.messages.append(serialize_ui_message({
            'role': 'assistant',
            'content': '附件如下',
            'media': [str(media_file)],
            'timestamp': '2026-03-08T12:00:00',
        }, session_key='webui:test-media'))
        loop.sessions.save(session)

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get(f'/api/media?path={media_file}&session_key=webui:test-media')
        assert resp.status_code == 200
        assert resp.content == b'fakepng'

    @pytest.mark.asyncio
    async def test_media_endpoint_uses_session_grant_cache(self, make_agent_loop, tmp_path, monkeypatch):
        from pathlib import Path

        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app
        from lemonclaw.gateway.webui.message_schema import serialize_ui_message

        loop, _bus = make_agent_loop()
        media_file = Path(loop.workspace) / 'cached.png'
        media_file.write_bytes(b'cached')
        session = loop.sessions.get_or_create('webui:test-cache')
        session.messages.append(serialize_ui_message({
            'role': 'assistant',
            'content': '附件如下',
            'media': [str(media_file)],
        }, session_key='webui:test-cache'))
        loop.sessions.save(session)

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        first = client.get(f'/api/media?path={media_file}&session_key=webui:test-cache')
        assert first.status_code == 200

        def bomb(_key):
            raise AssertionError('session should not be reloaded after media grant cache warms')

        monkeypatch.setattr(loop.sessions, '_load', bomb)
        second = client.get(f'/api/media?path={media_file}&session_key=webui:test-cache')
        assert second.status_code == 200

    @pytest.mark.asyncio
    async def test_media_endpoint_blocks_external_file(self, make_agent_loop, tmp_path):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        external = tmp_path.parent / 'outside.txt'
        external.write_text('secret', encoding='utf-8')

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get(f'/api/media?path={external}')
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_chat_stream_emits_outbound_media_event_and_persists_history(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from starlette.testclient import TestClient

        from lemonclaw.agent.loop import AgentLoop
        from lemonclaw.bus.queue import MessageBus
        from lemonclaw.gateway.server import create_app
        from lemonclaw.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = 'test-model'
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model='test-model', memory_window=10)
        tool_call = ToolCallRequest(
            id='call1', name='message',
            arguments={'content': 'Here is the file', 'channel': 'webui', 'chat_id': 'webui', 'media': ['/home/lemonclaw/.lemonclaw/media/demo.jpg']},
        )
        calls = iter([
            LLMResponse(content='', tool_calls=[tool_call]),
            LLMResponse(content='Done', tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        app = create_app(auth_token=None, agent_loop=loop, session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post('/api/chat/stream', json={'message': 'send file', 'session_key': 'webui:test'})
        assert resp.status_code == 200
        assert '"type": "outbound"' in resp.text or '"type":"outbound"' in resp.text
        assert 'demo.jpg' in resp.text
        assert 'mediaId' in resp.text
        assert 'blocks' in resp.text

        history = client.get('/api/sessions/webui%3Atest/messages')
        assert history.status_code == 200
        data = history.json()
        assistant = next(m for m in data['messages'] if m['role'] == 'assistant' and m.get('media'))
        assert assistant['media'][0]['filename'] == 'demo.jpg'
        assert any(block['type'] == 'media' for block in assistant['blocks'])

        raw_session = loop.sessions.get_or_create('webui:test')
        raw_assistant = next(m for m in raw_session.messages if m.get('role') == 'assistant' and m.get('media'))
        assert raw_assistant['media'][0]['filename'] == 'demo.jpg'
        assert any(block['type'] == 'media' for block in raw_assistant['blocks'])



    @pytest.mark.asyncio
    async def test_model_switch_requires_new_session_for_cross_provider_history(self, make_agent_loop):
        from lemonclaw.bus.events import InboundMessage

        loop, _bus = make_agent_loop(model='claude-sonnet-4-6')
        session = loop.sessions.get_or_create('telegram:chat1')
        session.messages.append({'role': 'user', 'content': 'hello'})
        reply = loop._handle_model_command(
            InboundMessage(channel='telegram', sender_id='u1', chat_id='chat1', content='/model gpt-5.2'),
            session,
            lang='en',
        )

        assert 'fresh session context' in reply.content.lower()
        assert session.messages == []
        assert session.metadata.get('current_model') == 'gpt-5.2'

class TestWebUIRoutes:
    """WebUI HTTP endpoint tests."""

    @pytest.mark.asyncio
    async def test_index_returns_html(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "LemonClaw" in resp.text

    @pytest.mark.asyncio
    async def test_auth_correct_token(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="test-secret", agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/auth", json={"token": "test-secret"})
        assert resp.status_code == 200
        assert "lc_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_auth_wrong_token(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="test-secret", agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/auth", json={"token": "wrong"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_sessions_requires_auth(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token="secret", agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get("/api/sessions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_models_returns_list(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0
        # No hidden models
        for m in data["models"]:
            assert "id" in m
            assert "label" in m
            assert "source" in m
            assert "profile" in m

    @pytest.mark.asyncio
    async def test_models_returns_runtime_current_meta(self, make_agent_loop, monkeypatch, tmp_path: Path):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app
        from lemonclaw.providers.catalog import apply_runtime_model_policy

        loop, bus = make_agent_loop()
        loop.model = 'gpt-4.1-mini'
        fake_config_path = tmp_path / 'config.json'
        monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)
        apply_runtime_model_policy({
            'defaults': {'chat': 'gpt-4.1-mini'},
            'catalog': [
                {'id': 'gpt-4.1-mini', 'label': 'GPT-4.1 Mini', 'tier': 'economy', 'enabled': True, 'visible': True, 'description': 'runtime'},
            ],
            'profiles': {'standard_chat': ['gpt-4.1-mini']},
            'sceneProfiles': {'chat': 'standard_chat'},
            'modelProfileOverrides': {},
        })
        try:
            app = create_app(auth_token=None, agent_loop=loop,
                             session_manager=loop.sessions, webui_enabled=True)
            client = TestClient(app)
            resp = client.get('/api/models')
            assert resp.status_code == 200
            data = resp.json()
            assert data['runtimePolicyActive'] is True
            assert data['current'] == 'gpt-4.1-mini'
            assert data['currentMeta']['source'] == 'runtime-policy'
            assert data['currentMeta']['profile'] == 'chat'
        finally:
            apply_runtime_model_policy(None)

    @pytest.mark.asyncio
    async def test_models_archives_old_webui_default_when_provider_family_drifts(self, make_agent_loop, monkeypatch, tmp_path: Path):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop(model='gpt-5.4')
        fake_config_path = tmp_path / 'config.json'
        fake_config_path.write_text(json.dumps({
            'agents': {
                'defaults': {
                    'model': 'gpt-5.4',
                },
            },
        }), encoding='utf-8')
        monkeypatch.setattr('lemonclaw.config.loader.get_config_path', lambda: fake_config_path)

        existing = loop.sessions.get_or_create('webui:default')
        existing.messages.append({'role': 'user', 'content': 'hello'})
        existing.metadata['current_model'] = 'claude-sonnet-4-6'
        loop.sessions.save(existing)

        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.get('/api/models')
        assert resp.status_code == 200

        fresh_default = loop.sessions.get_or_create('webui:default')
        assert fresh_default.messages == []
        assert fresh_default.metadata.get('current_model') == 'gpt-5.4'

        archived = [item for item in loop.sessions.list_sessions() if item['key'].startswith('webui:default:')]
        assert len(archived) == 1

    @pytest.mark.asyncio
    async def test_chat_stream_returns_sse(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        # Should contain a done event
        assert '"type": "done"' in resp.text or '"type":"done"' in resp.text

    @pytest.mark.asyncio
    async def test_chat_stream_surfaces_progress_kind(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()

        async def _fake_process_direct(*args, **kwargs):
            on_progress = kwargs["on_progress"]
            on_chunk = kwargs["on_chunk"]
            await on_progress("tool starts", tool_start=True)
            await on_chunk("chunk-1", first=True)
            return "done"

        loop.process_direct = _fake_process_direct

        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        assert '"progress_kind": "tool_start"' in resp.text or '"progress_kind":"tool_start"' in resp.text
        assert '"progress_kind": "chunk"' in resp.text or '"progress_kind":"chunk"' in resp.text

    @pytest.mark.asyncio
    async def test_chat_stream_cross_provider_switch_creates_new_webui_session(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop(model='claude-sonnet-4-6')
        existing = loop.sessions.get_or_create('webui:existing')
        existing.messages.append({'role': 'user', 'content': 'hello'})
        existing.metadata['current_model'] = 'claude-sonnet-4-6'
        loop.sessions.save(existing)

        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=True)
        client = TestClient(app)
        resp = client.post('/api/chat/stream', json={
            'message': 'switch provider',
            'session_key': 'webui:existing',
            'model': 'gpt-5.2',
        })
        assert resp.status_code == 200
        assert '"type": "done"' in resp.text or '"type":"done"' in resp.text
        assert '"session_key": "webui:' in resp.text or '"session_key":"webui:' in resp.text

        preserved = loop.sessions.get_or_create('webui:existing')
        assert preserved.messages == [{'role': 'user', 'content': 'hello'}]
        assert preserved.metadata.get('current_model') == 'claude-sonnet-4-6'

        sessions = [item for item in loop.sessions.list_sessions() if item['key'].startswith('webui:')]
        new_keys = [item['key'] for item in sessions if item['key'] != 'webui:existing']
        assert len(new_keys) == 1

        new_session = loop.sessions.get_or_create(new_keys[0])
        assert new_session.metadata.get('current_model') == 'gpt-5.2'
        assert any(message.get('role') == 'assistant' for message in new_session.messages)

    @pytest.mark.asyncio
    async def test_process_direct_uses_provider_for_session_model(self, make_agent_loop):
        from lemonclaw.providers.base import LLMResponse

        class RecordingProvider:
            def __init__(self, default_model: str, label: str):
                self.default_model = default_model
                self.label = label
                self.models: list[str | None] = []

            def get_default_model(self) -> str:
                return self.default_model

            async def chat(self, messages: list[dict], **kwargs):
                self.models.append(kwargs.get("model"))
                return LLMResponse(content=f"{self.label}:{kwargs.get('model')}")

        default_provider = RecordingProvider("gpt-5.4", "default")
        claude_provider = RecordingProvider("claude-sonnet-4-6", "claude")

        loop, _bus = make_agent_loop(
            provider=default_provider,
            model="gpt-5.4",
            provider_factory=lambda model=None: claude_provider if model == "claude-sonnet-4-6" else default_provider,
        )
        session = loop.sessions.get_or_create("webui:provider-switch")
        session.metadata["current_model"] = "claude-sonnet-4-6"
        loop.sessions.save(session)

        response = await loop.process_direct(
            "hello",
            session_key="webui:provider-switch",
            channel="webui",
            chat_id="webui",
        )

        assert response == "claude:claude-sonnet-4-6"
        assert default_provider.models == []
        assert claude_provider.models == ["claude-sonnet-4-6"]

    @pytest.mark.asyncio
    async def test_webui_disabled(self, make_agent_loop):
        from starlette.testclient import TestClient

        from lemonclaw.gateway.server import create_app

        loop, bus = make_agent_loop()
        app = create_app(auth_token=None, agent_loop=loop,
                         session_manager=loop.sessions, webui_enabled=False)
        client = TestClient(app)
        resp = client.get("/")
        # When webui disabled, / is not registered → 404 from Starlette
        assert resp.status_code in (404, 405)


def test_conductor_routes_require_valid_cookie(tmp_path):
    from types import SimpleNamespace

    from starlette.testclient import TestClient

    from lemonclaw.gateway.server import create_app
    from lemonclaw.gateway.webui.auth import create_session_cookie

    registry = SimpleNamespace(list_agents=lambda: [SimpleNamespace(agent_id='a1', role='worker', model='m', status=SimpleNamespace(value='idle'), skills=[], task_count=0, success_rate=1.0, last_active_ms=0, created_at_ms=0)])
    orchestrator = SimpleNamespace(active_plans=[])
    app = create_app(auth_token='secret-token', orchestrator=orchestrator, registry=registry)
    client = TestClient(app)

    assert client.get('/api/conductor/agents').status_code == 401
    cookie = create_session_cookie('secret-token')
    client.cookies.set('lc_session', cookie)
    resp = client.get('/api/conductor/agents')
    assert resp.status_code == 200
    assert resp.json()['agents'][0]['id'] == 'a1'
    templates = client.get('/api/conductor/templates')
    assert templates.status_code == 200
    payload = templates.json()
    assert any(item['id'] == 'general_swarm' for item in payload['templates'])


def test_conductor_plans_expose_swarm_handoff_snapshot(tmp_path):
    from starlette.testclient import TestClient

    from lemonclaw.conductor.types import (
        ArtifactRef,
        IntentAnalysis,
        ObservabilitySnapshot,
        OrchestrationPlan,
        OrchestratorPhase,
        PipelineStage,
        SubTask,
        SubTaskStatus,
        TaskComplexity,
    )
    from lemonclaw.gateway.server import create_app

    plan = OrchestrationPlan(
        request_id='plan-1',
        original_message='Ship the campaign package',
        intent=IntentAnalysis(
            complexity=TaskComplexity.COMPLEX,
            summary='Ship campaign package',
        ),
        phase=OrchestratorPhase.MONITORING,
        swarm_template_id='marketing_campaign_room',
        swarm_template_label='Marketing Campaign Room',
        swarm_goal='Ship a campaign package',
        planner=PipelineStage(status='completed', mode='orchestrator', summary='Ship campaign package'),
        merge=PipelineStage(status='pending', mode='merge', summary='Waiting for merge.'),
        evaluation=PipelineStage(status='accepted', mode='heuristic', summary='merged response accepted', score=0.92),
        artifacts=[ArtifactRef(artifact_id='plan-1:merged_result', kind='merged_result', title='Campaign package', preview='Top risk and landing page copy package')],
        observability=ObservabilitySnapshot(trace_id='orch:plan-1', execution_mode='conductor', started_at_ms=100, completed_at_ms=140, duration_ms=40),
        subtasks=[
            SubTask(
                id='t1',
                description='Audit the current funnel and summarize the risks',
                role_hint='strategist',
                assigned_agent_id='swarm-marketing_campaign_room-strategist',
                status=SubTaskStatus.COMPLETED,
                result='Top risk: unclear value proposition on hero section.',
                generator=PipelineStage(status='completed', mode='direct', summary='Top risk: unclear value proposition on hero section.', details={'output_kind': 'text', 'preview': 'Top risk: unclear value proposition on hero section.'}),
                evaluation=PipelineStage(status='accepted', mode='heuristic', summary='output accepted', score=0.92),
                artifacts=[ArtifactRef(artifact_id='t1:result', kind='subtask_result', title='Risk audit', preview='Top risk: unclear value proposition on hero section.')],
                observability=ObservabilitySnapshot(trace_id='orch:plan-1:t1', execution_mode='direct', attempt_count=1, started_at_ms=110, completed_at_ms=130, duration_ms=20, agent_id='swarm-marketing_campaign_room-strategist'),
            ),
            SubTask(
                id='t2',
                description='Draft the landing page copy package',
                role_hint='copywriter',
                assigned_agent_id='swarm-marketing_campaign_room-copywriter',
                depends_on=['t1'],
                status=SubTaskStatus.PENDING,
                generator=PipelineStage(status='pending', mode='direct', summary='Waiting on handoff.', details={'output_kind': 'text'}),
                evaluation=PipelineStage(status='needs_review', mode='heuristic', summary='waiting on handoff'),
                observability=ObservabilitySnapshot(execution_mode='direct', agent_id='swarm-marketing_campaign_room-copywriter', details={'queued_at_ms': 131, 'status': 'pending'}),
            ),
        ],
    )
    orchestrator = type('OrchestratorStub', (), {'active_plans': [plan]})()
    app = create_app(auth_token=None, orchestrator=orchestrator, registry=None)
    client = TestClient(app)

    resp = client.get('/api/conductor/plans')
    assert resp.status_code == 200
    payload = resp.json()
    current = payload['plans'][0]
    assert current['swarm_template_id'] == 'marketing_campaign_room'
    assert current['team_roles'][0]['id'] == 'lead'
    assert current['planner']['summary'] == 'Ship campaign package'
    assert current['generator']['completed_count'] == 1
    assert current['merge']['status'] == 'pending'
    assert current['evaluator']['plan_status'] == 'accepted'
    assert current['artifacts']['count'] == 2
    assert current['observability']['phase'] == 'monitoring'
    assert current['subtasks'][0]['role_label'] == 'Strategist'
    assert current['subtasks'][0]['state_bucket'] == 'completed'
    assert current['subtasks'][0]['result_preview'].startswith('Top risk:')
    assert current['subtasks'][0]['generator']['status'] == 'completed'
    assert current['subtasks'][0]['observability']['agent_id'] == 'swarm-marketing_campaign_room-strategist'
    assert current['subtasks'][0]['evaluation']['status'] == 'accepted'
    assert current['subtasks'][0]['artifact_count'] == 1
    assert current['subtasks'][1]['state_bucket'] == 'ready'
    assert current['subtasks'][1]['dependency_descriptions'] == ['Audit the current funnel and summarize the risks']


@pytest.mark.asyncio
async def test_agent_loop_refresh_runtime_config_reloads_git_and_http_tools(make_agent_loop):
    loop, _bus = make_agent_loop()
    config = Config()
    config.tools.git.auth_profiles = {
        "github": GitAuthProfileConfig(username="x-access-token", password="secret"),
    }
    config.tools.http.enabled = True
    config.tools.http.timeout = 45
    config.tools.http.allow_domains = ["api.example.com"]
    config.tools.http.auth_profiles = {
        "svc": {"Authorization": "Bearer abc"},
    }

    result = await loop.refresh_runtime_config(config, changed_paths=["tools.git", "tools.http"])

    git_tool = loop.tools.get("git")
    http_tool = loop.tools.get("http_request")
    assert result["git"]["status"] == "reloaded"
    assert result["http"]["status"] == "reloaded"
    assert git_tool is not None
    assert http_tool is not None
    assert git_tool.auth_profiles["github"]["password"] == "secret"
    assert http_tool._timeout == 45
