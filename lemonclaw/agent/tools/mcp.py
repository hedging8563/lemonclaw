"""MCP client: connects to MCP servers and wraps their tools as native lemonclaw tools."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from lemonclaw.agent.tools.base import Tool
from lemonclaw.agent.tools.registry import ToolRegistry


@dataclass
class _MCPBinding:
    session: Any
    reconnect: Any


class MCPToolWrapper(Tool):
    """Wraps a single MCP server tool as a lemonclaw Tool."""

    def __init__(self, binding: _MCPBinding, server_name: str, tool_def, tool_timeout: int = 30, binding_getter=None):
        self._binding = binding
        self._binding_getter = binding_getter or (lambda: self._binding)
        self._original_name = tool_def.name
        self._name = f"mcp_{server_name}_{tool_def.name}"
        self._description = tool_def.description or tool_def.name
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}
        self._tool_timeout = tool_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        from mcp import types
        try:
            binding = self._binding_getter()
            result = await asyncio.wait_for(
                binding.session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("MCP tool '{}' timed out after {}s", self._name, self._tool_timeout)
            try:
                await binding.reconnect()
            except Exception as reconnect_err:
                logger.warning("MCP tool '{}': reconnect after timeout failed: {}", self._name, reconnect_err)
            return f"(MCP tool call timed out after {self._tool_timeout}s)"
        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            elif hasattr(types, "ImageContent") and isinstance(block, types.ImageContent):
                mime = getattr(block, "mimeType", None) or getattr(block, "mime_type", None) or "image/*"
                parts.append(f"[image content: {mime}]")
            elif hasattr(types, "ResourceContent") and isinstance(block, types.ResourceContent):
                uri = getattr(block, "uri", None) or getattr(block, "resource", None) or "resource"
                text_hint = getattr(block, "text", None)
                parts.append(f"[resource content: {uri}]" + (f"\n{text_hint}" if text_hint else ""))
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


async def _probe_http_endpoint(url: str, headers: dict[str, str] | None, timeout: float = 10.0) -> str | None:
    """Pre-flight check for HTTP MCP endpoints. Returns error message or None if OK."""
    try:
        async with httpx.AsyncClient(
            headers=headers or None,
            follow_redirects=True,
            timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout),
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 401:
                return f"401 Unauthorized (check credentials/headers)"
            if resp.status_code == 403:
                return f"403 Forbidden"
            # Other status codes (404, 405, etc.) are OK — the MCP endpoint
            # may only accept POST, so non-2xx on GET is expected.
            return None
    except httpx.ConnectError as e:
        return f"connection failed: {e}"
    except httpx.TimeoutException:
        return f"connection timed out after {timeout}s"
    except Exception as e:
        return f"probe error: {e}"


async def connect_mcp_servers(
    mcp_servers: dict,
    registry: ToolRegistry,
    stack: AsyncExitStack,
    *,
    workspace: Path | None = None,
) -> None:
    """Connect to configured MCP servers and register their tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    bindings: dict[str, _MCPBinding] = {}
    _reconnect_locks: dict[str, asyncio.Lock] = {}

    for name, cfg in mcp_servers.items():
        _reconnect_locks[name] = asyncio.Lock()
        try:
            # For HTTP endpoints, probe reachability before entering
            # streamable_http_client. This avoids a known anyio bug where
            # a failed streamable_http_client async generator causes
            # "Attempted to exit cancel scope in a different task" RuntimeError
            # during cleanup, which crashes the entire process.
            if cfg.url and not cfg.command:
                probe_err = await _probe_http_endpoint(cfg.url, cfg.headers)
                if probe_err:
                    logger.error("MCP server '{}': endpoint unreachable ({}), skipping", name, probe_err)
                    continue

            async def _open_session(name=name, cfg=cfg):
                if cfg.command:
                    params = StdioServerParameters(
                        command=cfg.command,
                        args=cfg.args,
                        env=cfg.env or None,
                        cwd=str(workspace) if workspace else None,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                elif cfg.url:
                    from mcp.client.streamable_http import streamable_http_client
                    http_client = await stack.enter_async_context(
                        httpx.AsyncClient(
                            headers=cfg.headers or None,
                            follow_redirects=True,
                            timeout=httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0),
                        )
                    )
                    read, write, _ = await stack.enter_async_context(
                        streamable_http_client(cfg.url, http_client=http_client)
                    )
                else:
                    logger.warning("MCP server '{}': no command or url configured, skipping", name)
                    return None

                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                return session

            session = await _open_session()
            if session is None:
                continue

            binding = _MCPBinding(session=session, reconnect=None)
            bindings[name] = binding

            async def _reconnect(open_session=_open_session, server_name=name):
                async with _reconnect_locks[server_name]:
                    current = bindings[server_name]
                    close_fn = getattr(current.session, 'aclose', None) or getattr(current.session, 'close', None)
                    if close_fn:
                        maybe = close_fn()
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    new_session = await open_session()
                    if new_session is None:
                        raise RuntimeError(f"MCP server '{server_name}' is no longer available")
                    bindings[server_name] = _MCPBinding(session=new_session, reconnect=_reconnect)

            binding.reconnect = _reconnect

            tools = await session.list_tools()
            for tool_def in tools.tools:
                wrapper = MCPToolWrapper(
                    binding,
                    name,
                    tool_def,
                    tool_timeout=cfg.tool_timeout,
                    binding_getter=lambda server_name=name: bindings[server_name],
                )
                registry.register(wrapper)
                logger.debug("MCP: registered tool '{}' from server '{}'", wrapper.name, name)

            logger.info("MCP server '{}': connected, {} tools registered", name, len(tools.tools))
        except (Exception, BaseExceptionGroup) as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)
