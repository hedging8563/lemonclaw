from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace

import pytest

from lemonclaw.agent.tools.mcp import connect_mcp_servers
from lemonclaw.agent.tools.registry import ToolRegistry
from lemonclaw.config.schema import ToolsConfig
from lemonclaw.gateway.webui.settings import _RESTART_FIELDS


@pytest.mark.asyncio
async def test_connect_mcp_servers_uses_workspace_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import mcp
    import mcp.client.stdio as mcp_stdio

    captured: dict[str, object] = {}

    class FakeParams:
        def __init__(self, **kwargs):
            captured["params"] = SimpleNamespace(**kwargs)

    @asynccontextmanager
    async def fake_stdio_client(params):
        captured["stdio_params"] = params
        yield ("read", "write")

    class FakeSession:
        def __init__(self, read, write):
            self.read = read
            self.write = write

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="ping",
                        description="Ping",
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
            )

    monkeypatch.setattr(mcp, "StdioServerParameters", FakeParams)
    monkeypatch.setattr(mcp, "ClientSession", FakeSession)
    monkeypatch.setattr(mcp_stdio, "stdio_client", fake_stdio_client)

    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        await connect_mcp_servers(
            {"filesystem": SimpleNamespace(command="npx", args=["@mcp/server-filesystem"], env={}, tool_timeout=30, url="", headers={})},
            registry,
            stack,
            workspace=tmp_path,
        )

    params = captured["params"]
    assert getattr(params, "cwd") == str(tmp_path)
    assert registry.has("mcp_filesystem_ping")


def test_exec_settings_require_restart() -> None:
    assert _RESTART_FIELDS.match("tools.exec")


@pytest.mark.asyncio
async def test_mcp_timeout_reconnects_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    from lemonclaw.agent.tools.mcp import MCPToolWrapper, _MCPBinding

    class SlowSession:
        def __init__(self):
            self.closed = False

        async def call_tool(self, name, arguments=None):
            await asyncio.sleep(0.05)

        async def aclose(self):
            self.closed = True

    session = SlowSession()
    reconnected = []

    async def _reconnect():
        reconnected.append(True)

    binding = _MCPBinding(session=session, reconnect=_reconnect)
    tool_def = SimpleNamespace(name='ping', description='Ping', inputSchema={'type': 'object', 'properties': {}})
    wrapper = MCPToolWrapper(binding, 'filesystem', tool_def, tool_timeout=0.01)

    result = await wrapper.execute()
    assert 'timed out' in result
    assert reconnected == [True]
