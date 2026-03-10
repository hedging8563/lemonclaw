from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace

import pytest

from lemonclaw.agent.tools.mcp import connect_mcp_servers
from lemonclaw.agent.tools.registry import ToolRegistry
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


@pytest.mark.asyncio
async def test_connect_mcp_servers_reconnect_uses_original_binding(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import mcp
    import mcp.client.stdio as mcp_stdio

    opened: list[tuple[str, tuple[str, ...]]] = []

    class FakeParams:
        def __init__(self, **kwargs):
            self.command = kwargs.get('command')
            self.args = tuple(kwargs.get('args') or [])
            self.env = kwargs.get('env')
            self.cwd = kwargs.get('cwd')

    counter = {'value': 0}

    @asynccontextmanager
    async def fake_stdio_client(params):
        opened.append((params.command, tuple(params.args)))
        yield (f'read-{len(opened)}', f'write-{len(opened)}')

    class FakeSession:
        def __init__(self, read, write):
            self.read = read
            self.write = write
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            counter['value'] += 1
            name = 'alpha_tool' if counter['value'] == 1 else 'beta_tool'
            return SimpleNamespace(tools=[SimpleNamespace(name=name, description=name, inputSchema={'type': 'object', 'properties': {}})])

        async def call_tool(self, name, arguments=None):
            await asyncio.sleep(0.05)

        async def aclose(self):
            return None

    monkeypatch.setattr(mcp, 'StdioServerParameters', FakeParams)
    monkeypatch.setattr(mcp, 'ClientSession', FakeSession)
    monkeypatch.setattr(mcp_stdio, 'stdio_client', fake_stdio_client)

    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        await connect_mcp_servers(
            {
                'alpha': SimpleNamespace(command='cmd-a', args=['--a'], env={}, tool_timeout=0.01, url='', headers={}),
                'beta': SimpleNamespace(command='cmd-b', args=['--b'], env={}, tool_timeout=0.01, url='', headers={}),
            },
            registry,
            stack,
            workspace=tmp_path,
        )

        wrapper = registry.get('mcp_alpha_alpha_tool')
        assert wrapper is not None
        result = await wrapper.execute()
        assert 'timed out' in result

    assert opened[:2] == [('cmd-a', ('--a',)), ('cmd-b', ('--b',))]
    assert opened[2] == ('cmd-a', ('--a',))


@pytest.mark.asyncio
async def test_mcp_wrapper_formats_resource_and_image_content(monkeypatch: pytest.MonkeyPatch) -> None:
    from lemonclaw.agent.tools.mcp import MCPToolWrapper, _MCPBinding

    class FakeTypes:
        class TextContent:
            def __init__(self, text: str):
                self.text = text

        class ResourceContent:
            def __init__(self, uri: str, text: str = ''):
                self.uri = uri
                self.text = text

        class ImageContent:
            def __init__(self, mime_type: str):
                self.mime_type = mime_type

    class Session:
        async def call_tool(self, name, arguments=None):
            return SimpleNamespace(content=[
                FakeTypes.TextContent('hello'),
                FakeTypes.ResourceContent('file:///tmp/demo.txt', 'resource body'),
                FakeTypes.ImageContent('image/png'),
            ])

    async def _noop():
        return None

    binding = _MCPBinding(session=Session(), reconnect=_noop)
    tool_def = SimpleNamespace(name='inspect', description='Inspect', inputSchema={'type': 'object', 'properties': {}})
    wrapper = MCPToolWrapper(binding, 'demo', tool_def, tool_timeout=1)

    import sys
    monkeypatch.setitem(sys.modules, 'mcp', SimpleNamespace(types=FakeTypes))
    result = await wrapper.execute()
    assert 'hello' in result
    assert '[resource content: file:///tmp/demo.txt]' in result
    assert 'resource body' in result
    assert '[image content: image/png]' in result



@pytest.mark.asyncio
async def test_connect_mcp_servers_reconnect_uses_latest_binding_lookup(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import mcp
    import mcp.client.stdio as mcp_stdio

    sessions = []

    class FakeParams:
        def __init__(self, **kwargs):
            self.command = kwargs.get('command')
            self.args = tuple(kwargs.get('args') or [])

    @asynccontextmanager
    async def fake_stdio_client(params):
        yield ('read', 'write')

    class FakeSession:
        def __init__(self, read, write):
            self.label = f'session-{len(sessions)+1}'
            sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name='ping', description='Ping', inputSchema={'type': 'object', 'properties': {}})])

        async def call_tool(self, name, arguments=None):
            if self.label == 'session-1':
                await asyncio.sleep(0.05)
            return SimpleNamespace(content=[])

        async def aclose(self):
            return None

    monkeypatch.setattr(mcp, 'StdioServerParameters', FakeParams)
    monkeypatch.setattr(mcp, 'ClientSession', FakeSession)
    monkeypatch.setattr(mcp_stdio, 'stdio_client', fake_stdio_client)

    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        await connect_mcp_servers(
            {'alpha': SimpleNamespace(command='cmd-a', args=['--a'], env={}, tool_timeout=0.01, url='', headers={})},
            registry,
            stack,
            workspace=tmp_path,
        )

        wrapper = registry.get('mcp_alpha_ping')
        assert wrapper is not None
        result = await wrapper.execute()
        assert 'timed out' in result
        assert len(sessions) == 2
        assert wrapper._binding_getter().session is sessions[-1]
