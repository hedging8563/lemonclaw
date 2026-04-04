"""Test message tool suppress logic for final replies."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from lemonclaw.agent.loop import AgentLoop
from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.bus.events import InboundMessage, OutboundMessage
from lemonclaw.bus.queue import MessageBus
from lemonclaw.providers.base import LLMResponse, ToolCallRequest


class _GovernanceConfig:
    enabled = True
    default_autonomy_cap = "L1"
    token_ttl_seconds = 60
    kill_switch_file = ""
    audit_log_path = ""
    budgets = type("Budgets", (), {"default_task_usd": None})()
    capability_overrides: dict[str, dict[str, object]] = {}


class _SystemTokenTool(Tool):
    @property
    def name(self) -> str:
        return "system_token_tool"

    @property
    def description(self) -> str:
        return "Report whether a capability token reached the tool call."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
        }

    async def execute(self, value: str, _capability_token=None, **kwargs):
        del kwargs
        return f"{value}:{'token-present' if _capability_token is not None else 'token-missing'}"


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)


def _make_governed_loop(tmp_path: Path) -> AgentLoop:
    cfg = _GovernanceConfig()
    cfg.kill_switch_file = str(tmp_path / "governance.json")
    cfg.audit_log_path = str(tmp_path / "audit.jsonl")
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
        governance_config=cfg,
    )


class TestMessageToolSuppressLogic:
    """Final reply suppressed only when message tool sends to the same target."""

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert result is None  # suppressed

    @pytest.mark.asyncio
    async def test_suppress_when_message_tool_queues_same_target_outbox(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.outbox_enabled = True
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        loop.ledger.ensure_task(
            task_id="task_msg_1",
            session_key="feishu:chat123",
            agent_id=loop.agent_id,
            mode="chat",
            channel="feishu",
            goal="Send",
        )
        msg = InboundMessage(
            channel="feishu",
            sender_id="user1",
            chat_id="chat123",
            content="Send",
            metadata={"_task_id": "task_msg_1"},
        )
        result = await loop._process_message(msg)

        assert len(sent) == 0
        assert result is None
        events = loop.ledger.list_outbox_events()
        assert len(events) == 1
        assert events[0]["effect_type"] == "outbound_message"

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Email content", "channel": "email", "chat_id": "user@example.com"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="I've sent the email.", tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send email")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert sent[0].channel == "email"
        assert result is not None  # not suppressed
        assert result.channel == "feishu"


class TestEmptyToolCallGuidance:
    def test_coding_empty_dict_gets_specific_guidance(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        guidance = loop._empty_tool_call_guidance(
            "coding",
            {},
            "Error: Invalid parameters for tool 'coding': missing required task",
            "en",
        )
        assert guidance is not None
        assert "required task" in guidance
        assert "exec/write_file" in guidance

    def test_coding_none_arguments_also_fail_fast(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        guidance = loop._empty_tool_call_guidance(
            "coding",
            None,
            "Error: Invalid parameters for tool 'coding': missing required task",
            "zh",
        )
        assert guidance is not None
        assert "缺少必要的 task" in guidance

    def test_browser_empty_arguments_get_specific_guidance(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        guidance = loop._empty_tool_call_guidance(
            "browser",
            {},
            "Error: Invalid parameters for tool 'browser': missing required command",
            "en",
        )
        assert guidance is not None
        assert "required command" in guidance
        assert "snapshot -i" in guidance

    def test_nonempty_arguments_with_non_missing_required_error_do_not_trigger_guidance(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        guidance = loop._empty_tool_call_guidance(
            "coding",
            {"task": "finish module"},
            "Error: Invalid parameters for tool 'coding': task must be at least 10 chars",
            "en",
        )
        assert guidance is None

    @pytest.mark.parametrize(
        ("tool_name", "missing_fields"),
        [
            ("analyze_image", ("path",)),
            ("browser", ("command",)),
            ("coding", ("task",)),
            ("create_agent", ("agent_id", "role")),
            ("cron", ("action",)),
            ("db", ("connection_profile", "query")),
            ("edit_file", ("path", "old_text", "new_text")),
            ("exec", ("command",)),
            ("get_agent_status", ("agent_id",)),
            ("git", ("action",)),
            ("glob", ("pattern",)),
            ("grep", ("pattern",)),
            ("http_request", ("method", "url")),
            ("k8s", ("action",)),
            ("list_dir", ("path",)),
            ("message", ("content",)),
            ("notify", ("target_type", "content")),
            ("read_attachment", ("path",)),
            ("read_file", ("path",)),
            ("search_knowledge", ("query",)),
            ("send_to_agent", ("agent_id", "message")),
            ("spawn", ("task",)),
            ("task_checkpoint", ("stage", "summary")),
            ("web_fetch", ("url",)),
            ("web_search", ("query",)),
            ("write_file", ("path", "content")),
        ],
    )
    def test_all_builtin_tools_with_required_fields_fail_fast(self, tmp_path: Path, tool_name: str, missing_fields: tuple[str, ...]) -> None:
        loop = _make_loop(tmp_path)
        missing_msg = "; ".join(f"missing required {field}" for field in missing_fields)
        guidance = loop._empty_tool_call_guidance(
            tool_name,
            None,
            f"Error: Invalid parameters for tool '{tool_name}': {missing_msg}",
            "en",
        )
        assert guidance is not None, tool_name
        if tool_name not in {"write_file", "exec", "coding", "browser"}:
            for field in missing_fields:
                assert field in guidance

    def test_list_agents_without_required_fields_does_not_trigger_guidance(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        guidance = loop._empty_tool_call_guidance(
            "list_agents",
            None,
            "Error: Invalid parameters for tool 'list_agents': parameter should be object",
            "en",
        )
        assert guidance is None


class TestSystemMessageToolContext:
    @pytest.mark.asyncio
    async def test_system_messages_provide_capability_token_to_tools(self, tmp_path: Path) -> None:
        loop = _make_governed_loop(tmp_path)
        loop.tools.register(_SystemTokenTool())

        calls = iter([
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call-system-1",
                        name="system_token_tool",
                        arguments={"value": "system-check"},
                    )
                ],
            ),
            LLMResponse(content="system-check:token-present", tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))

        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="weixin:chat123",
            content="Please verify the tool context.",
            session_key_override="weixin:chat123",
        )

        result = await loop._process_message(msg)

        assert result is not None
        assert result.channel == "weixin"
        assert result.chat_id == "chat123"
        assert result.content == "system-check:token-present"

    @pytest.mark.asyncio
    async def test_tool_call_preamble_is_not_reused_as_final_reply(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1",
            name="read_file",
            arguments={"path": "image.jpg"},
        )
        calls = iter([
            LLMResponse(content="我来帮你识别图片中的文字内容。", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="请识别图片里的文字")
        result = await loop._process_message(msg)

        assert result is not None
        assert result.content == "处理完成，但没有需要回复的内容。"
        assert "我来帮你识别图片中的文字内容" not in result.content

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content


class TestMessageToolTurnTracking:

    def test_start_turn_returns_fresh_tracking_state(self) -> None:
        first = MessageTool.start_turn()
        second = MessageTool.start_turn()

        first["sent"] = True
        first["messages"].append("hello")

        assert second == {"sent": False, "messages": []}
