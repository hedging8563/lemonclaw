from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from lemonclaw.agent.loop import AgentLoop, _BUILTIN_TOOL_REQUIRED_FIELDS
from lemonclaw.agent.tools.agent_ops import (
    CreateAgentTool,
    GetAgentStatusTool,
    ListAgentsTool,
    SendToAgentTool,
)
from lemonclaw.agent.tools.browser import BrowserTool
from lemonclaw.agent.tools.coding import CodingTool
from lemonclaw.agent.tools.cron import CronTool
from lemonclaw.agent.tools.db import DBTool
from lemonclaw.agent.tools.filesystem import (
    AnalyzeImageTool,
    EditFileTool,
    ListDirTool,
    ReadAttachmentTool,
    ReadFileTool,
    WriteFileTool,
)
from lemonclaw.agent.tools.git_tool import GitTool
from lemonclaw.agent.tools.glob import GlobTool
from lemonclaw.agent.tools.grep import GrepTool
from lemonclaw.agent.tools.http_request import HTTPRequestTool
from lemonclaw.agent.tools.k8s import K8sTool
from lemonclaw.agent.tools.knowledge import KnowledgeSearchTool
from lemonclaw.agent.tools.lemondata_nonchat import LemonDataNonChatTool
from lemonclaw.agent.tools.message import MessageTool
from lemonclaw.agent.tools.notify import NotifyTool
from lemonclaw.agent.tools.shell import ExecTool
from lemonclaw.agent.tools.spawn import SpawnTool
from lemonclaw.agent.tools.task_checkpoint import TaskCheckpointTool
from lemonclaw.agent.tools.web import WebFetchTool, WebSearchTool
from lemonclaw.bus.queue import MessageBus


def _all_builtin_tools(tmp_path: Path):
    registry = MagicMock()
    registry.list_agents.return_value = []
    bus = AsyncMock()
    manager = MagicMock()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    cron_service = MagicMock()

    return [
        AnalyzeImageTool(provider=provider, workspace=tmp_path),
        BrowserTool(workspace=tmp_path),
        CodingTool(working_dir=str(tmp_path)),
        CreateAgentTool(registry=registry),
        CronTool(cron_service=cron_service),
        DBTool(sqlite_profiles={}, postgres_profiles={}),
        EditFileTool(workspace=tmp_path),
        ExecTool(working_dir=str(tmp_path)),
        GetAgentStatusTool(registry=registry),
        GitTool(working_dir=str(tmp_path)),
        GlobTool(workspace=tmp_path),
        GrepTool(workspace=tmp_path),
        HTTPRequestTool(),
        K8sTool(),
        KnowledgeSearchTool(workspace=str(tmp_path)),
        LemonDataNonChatTool(),
        ListAgentsTool(registry=registry),
        ListDirTool(workspace=tmp_path),
        MessageTool(send_callback=bus),
        NotifyTool(send_callback=bus),
        ReadAttachmentTool(workspace=tmp_path),
        ReadFileTool(workspace=tmp_path),
        SendToAgentTool(registry=registry, bus=bus),
        SpawnTool(manager=manager),
        TaskCheckpointTool(),
        WebFetchTool(),
        WebSearchTool(api_key=""),
        WriteFileTool(workspace=tmp_path),
    ]


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", memory_window=10)


def test_builtin_required_fields_map_matches_all_tool_schemas(tmp_path: Path) -> None:
    tools = _all_builtin_tools(tmp_path)

    tool_names = {tool.name for tool in tools}
    assert len(tool_names) == 28
    assert tool_names == set(_BUILTIN_TOOL_REQUIRED_FIELDS.keys())

    for tool in tools:
        params = tool.parameters or {}
        required = tuple(params.get("required", []))
        assert required == _BUILTIN_TOOL_REQUIRED_FIELDS[tool.name], tool.name


def test_agent_ops_tools_use_fallback_guidance_even_when_not_registered(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)

    create_guidance = loop._empty_tool_call_guidance(
        "create_agent",
        None,
        "Error: Invalid parameters for tool 'create_agent': missing required agent_id; missing required role",
        "en",
    )
    assert create_guidance is not None
    assert "agent_id" in create_guidance
    assert "role" in create_guidance

    send_guidance = loop._empty_tool_call_guidance(
        "send_to_agent",
        None,
        "Error: Invalid parameters for tool 'send_to_agent': missing required agent_id; missing required message",
        "en",
    )
    assert send_guidance is not None
    assert "agent_id" in send_guidance
    assert "message" in send_guidance

    status_guidance = loop._empty_tool_call_guidance(
        "get_agent_status",
        None,
        "Error: Invalid parameters for tool 'get_agent_status': missing required agent_id",
        "en",
    )
    assert status_guidance is not None
    assert "agent_id" in status_guidance

    list_guidance = loop._empty_tool_call_guidance(
        "list_agents",
        None,
        "Error: Invalid parameters for tool 'list_agents': parameter should be object",
        "en",
    )
    assert list_guidance is None
