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


def _merge_object_schema_branches(branches: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    warnings: list[str] = []
    additional_properties: bool | dict[str, Any] = True

    for branch in branches:
        branch_type = branch.get("type")
        if branch_type not in (None, "object"):
            return None, ["allOf contains a non-object branch"]
        branch_props = branch.get("properties", {})
        if isinstance(branch_props, dict):
            properties.update(branch_props)
        required.extend(str(item) for item in branch.get("required", []) if item)
        branch_additional = branch.get("additionalProperties", True)
        if branch_additional is False:
            additional_properties = False
        elif isinstance(branch_additional, dict) and additional_properties is True:
            additional_properties = branch_additional
        elif isinstance(branch_additional, dict) and isinstance(additional_properties, dict):
            warnings.append("allOf merged multiple additionalProperties schemas; keeping the first one")

    normalized: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        normalized["required"] = sorted(dict.fromkeys(required))
    if additional_properties is not True:
        normalized["additionalProperties"] = additional_properties
    return normalized, warnings


def _normalize_mcp_schema(
    schema: Any,
    *,
    path: str = "input",
    require_object: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}, [f"{path} schema was not an object; falling back to empty object schema"]

    normalized = dict(schema)
    for combiner in ("oneOf", "anyOf"):
        if isinstance(normalized.get(combiner), list):
            branches = []
            for index, branch in enumerate(normalized[combiner]):
                next_branch, branch_warnings = _normalize_mcp_schema(
                    branch,
                    path=f"{path}.{combiner}[{index}]",
                    require_object=False,
                )
                branches.append(next_branch)
                warnings.extend(branch_warnings)
            normalized[combiner] = branches

    if isinstance(normalized.get("allOf"), list):
        branches = []
        for index, branch in enumerate(normalized["allOf"]):
            next_branch, branch_warnings = _normalize_mcp_schema(
                branch,
                path=f"{path}.allOf[{index}]",
                require_object=False,
            )
            branches.append(next_branch)
            warnings.extend(branch_warnings)
        merged, merge_warnings = _merge_object_schema_branches(branches)
        if merged is not None:
            parent_props = normalized.get("properties", {})
            parent_required = normalized.get("required", [])
            parent_additional = normalized.get("additionalProperties", True)
            parent_type = normalized.get("type")
            normalized.pop("allOf", None)
            normalized["properties"] = {
                **(parent_props if isinstance(parent_props, dict) else {}),
                **(merged.get("properties", {}) if isinstance(merged.get("properties"), dict) else {}),
            }
            merged_required = list(merged.get("required", [])) if isinstance(merged.get("required"), list) else []
            combined_required = [
                *[str(item) for item in parent_required if item],
                *[str(item) for item in merged_required if item],
            ]
            if combined_required:
                normalized["required"] = sorted(dict.fromkeys(combined_required))
            elif "required" in normalized:
                normalized.pop("required", None)
            if parent_type is None:
                normalized["type"] = merged.get("type", "object")
            else:
                normalized["type"] = parent_type
            merged_additional = merged.get("additionalProperties", True)
            if parent_additional is False:
                normalized["additionalProperties"] = False
            elif isinstance(parent_additional, dict):
                normalized["additionalProperties"] = parent_additional
            elif merged_additional is not True:
                normalized["additionalProperties"] = merged_additional
            else:
                normalized.pop("additionalProperties", None)
            warnings.extend(merge_warnings)
        else:
            normalized["allOf"] = branches
            warnings.extend(merge_warnings)

    branch_type = normalized.get("type")
    if branch_type is None and ("properties" in normalized or "required" in normalized):
        normalized["type"] = "object"

    if isinstance(branch_type, list) and "null" in branch_type:
        normalized["type"] = branch_type

    if isinstance(normalized.get("properties"), dict):
        normalized["properties"] = {
            key: _normalize_mcp_schema(value, path=f"{path}.properties.{key}", require_object=False)[0]
            for key, value in normalized["properties"].items()
        }

    if isinstance(normalized.get("items"), dict):
        normalized["items"] = _normalize_mcp_schema(
            normalized["items"],
            path=f"{path}.items",
            require_object=False,
        )[0]

    if isinstance(normalized.get("additionalProperties"), dict):
        normalized["additionalProperties"] = _normalize_mcp_schema(
            normalized["additionalProperties"],
            path=f"{path}.additionalProperties",
            require_object=False,
        )[0]

    if require_object and normalized.get("type") != "object":
        return {"type": "object", "properties": {}}, [
            *warnings,
            f"{path} schema is not an object schema; falling back to empty object schema",
        ]
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
    return normalized, warnings


def _format_schema_compatibility_notes(warnings: list[str]) -> str:
    """Render schema compatibility warnings in a stable, agent-readable format."""
    unique_warnings = list(dict.fromkeys(warnings))
    if not unique_warnings:
        return ""
    lines = ["", "Compatibility diagnostics:", "Compatibility section:"]
    lines.append("- status=degraded")
    lines.append(f"- warning_count={len(unique_warnings)}")
    lines.append("Compatibility warnings:")
    lines.extend(f"- warning={warning}" for warning in unique_warnings)
    return "\n".join(lines)


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
        self._parameters, warnings = _normalize_mcp_schema(
            tool_def.inputSchema or {"type": "object", "properties": {}},
            require_object=True,
        )
        self._schema_warnings = tuple(dict.fromkeys(warnings))
        self._compatibility_status = "compatible" if not self._schema_warnings else "degraded"
        self._compatibility_profile = "mcp_schema_normalization"
        self._description = f"{self._description}{_format_schema_compatibility_notes(warnings)}"
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

    @property
    def compatibility_status(self) -> str:
        return self._compatibility_status

    @property
    def compatibility_profile(self) -> str:
        return self._compatibility_profile

    @property
    def compatibility_warnings(self) -> tuple[str, ...]:
        return self._schema_warnings

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
            # Only inspect response headers so SSE endpoints do not look "timed out"
            # just because they keep the stream open.
            async with client.stream("GET", url) as response:
                if response.status_code == 401:
                    return "401 Unauthorized (check credentials/headers)"
                if response.status_code == 403:
                    return "403 Forbidden"
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
                    # Probe before every HTTP connect attempt, including reconnects.
                    # This avoids entering streamable_http_client when auth/connectivity
                    # failures would trigger the anyio cleanup bug.
                    probe_err = await _probe_http_endpoint(cfg.url, cfg.headers)
                    if probe_err:
                        logger.error("MCP server '{}': HTTP pre-flight failed ({}), skipping", name, probe_err)
                        return None

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
