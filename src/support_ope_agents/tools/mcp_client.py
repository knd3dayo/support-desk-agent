from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import anyio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from support_ope_agents.config import AppConfig, McpConfigError, McpManifest, McpServerConfig, McpToolBinding

ToolConfigurationError = McpConfigError


@dataclass(frozen=True, slots=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


class McpToolClient:
    def __init__(self, manifest: McpManifest, default_timeout_seconds: float = 30.0):
        self._manifest = manifest
        self._default_timeout_seconds = default_timeout_seconds
        self._client = MultiServerMCPClient(
            connections={
                server_name: self._build_connection(server_config)
                for server_name, server_config in manifest.servers.items()
            },
            tool_name_prefix=False,
        )
        self._tool_name_cache: dict[str, set[str]] = {}
        self._tool_cache: dict[str, tuple[McpToolInfo, ...]] = {}

    @classmethod
    def from_config(cls, config: AppConfig) -> "McpToolClient":
        manifest_path = config.tools.mcp_manifest_path
        if manifest_path is None:
            raise ToolConfigurationError("tools.mcp_manifest_path is required when enabled logical tools use provider='mcp'")
        return cls(McpManifest.load(manifest_path), default_timeout_seconds=config.tools.mcp_timeout_seconds)

    def validate_binding(self, *, role: str, logical_tool_name: str, binding: McpToolBinding) -> None:
        if binding.server not in self._manifest.servers:
            available = ", ".join(sorted(self._manifest.servers)) or "<none>"
            raise ToolConfigurationError(
                f"{role}.{logical_tool_name} references unknown MCP server '{binding.server}'. "
                f"manifest={self._manifest.path} available_servers=[{available}]"
            )

        available_tools = self.list_tool_names(binding.server)
        if binding.tool not in available_tools:
            tools_text = ", ".join(sorted(available_tools)) or "<none>"
            raise ToolConfigurationError(
                f"{role}.{logical_tool_name} references unknown MCP tool '{binding.tool}'. "
                f"server='{binding.server}' manifest={self._manifest.path} available_tools=[{tools_text}]"
            )

    def validate_logical_tool(self, *, logical_tool_name: str, binding: McpToolBinding) -> None:
        self.validate_binding(role="tools.logical_tools", logical_tool_name=logical_tool_name, binding=binding)

    def build_handler(
        self,
        binding: McpToolBinding,
        logical_tool_name: str,
        *,
        static_arguments: dict[str, Any] | None = None,
        argument_map: dict[str, str] | None = None,
        integer_arguments: tuple[str, ...] = (),
    ) -> Callable[..., Any]:
        resolved_static_arguments = dict(static_arguments or {})
        resolved_argument_map = dict(argument_map or {})

        async def _handler(*args: object, **kwargs: object) -> str:
            if args:
                raise TypeError(
                    f"MCP-backed tool '{logical_tool_name}' accepts keyword arguments only. Received positional args: {len(args)}"
                )
            prepared_arguments = dict(resolved_static_arguments)
            for name, value in kwargs.items():
                prepared_arguments[resolved_argument_map.get(name, name)] = value

            for name in integer_arguments:
                if name not in prepared_arguments:
                    continue
                value = prepared_arguments[name]
                if isinstance(value, bool) or isinstance(value, int):
                    continue
                if isinstance(value, str):
                    stripped = value.strip()
                    if not stripped:
                        continue
                    try:
                        prepared_arguments[name] = int(stripped)
                    except ValueError as exc:
                        raise ValueError(
                            f"MCP-backed tool '{logical_tool_name}' requires integer argument '{name}', but received {value!r}"
                        ) from exc
                    continue
                raise ValueError(
                    f"MCP-backed tool '{logical_tool_name}' requires integer argument '{name}', but received {type(value).__name__}"
                )

            result = await self._call_tool_async(binding.server, binding.tool, prepared_arguments)
            return self._serialize_call_result(result)

        _handler.__name__ = logical_tool_name
        return _handler

    def list_tools(self, server_name: str) -> tuple[McpToolInfo, ...]:
        if server_name in self._tool_cache:
            return self._tool_cache[server_name]

        if server_name not in self._manifest.servers:
            available = ", ".join(sorted(self._manifest.servers)) or "<none>"
            raise ToolConfigurationError(
                f"unknown MCP server '{server_name}'. manifest={self._manifest.path} available_servers=[{available}]"
            )

        server = self._manifest.servers[server_name]
        try:
            tools = anyio.run(self._list_tools_async, server)
        except Exception as exc:
            raise ToolConfigurationError(
                f"Failed to query MCP server '{server_name}' from manifest={self._manifest.path}: {exc}"
            ) from exc

        self._tool_cache[server_name] = tools
        self._tool_name_cache[server_name] = {tool.name for tool in tools}
        return tools

    def list_tool_names(self, server_name: str) -> set[str]:
        if server_name in self._tool_name_cache:
            return self._tool_name_cache[server_name]
        return {tool.name for tool in self.list_tools(server_name)}

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        available_tools = self.list_tool_names(server_name)
        if tool_name not in available_tools:
            tools_text = ", ".join(sorted(available_tools)) or "<none>"
            raise ToolConfigurationError(
                f"unknown MCP tool '{tool_name}' for server='{server_name}'. available_tools=[{tools_text}]"
            )
        try:
            result = anyio.run(self._call_tool_async, server_name, tool_name, arguments)
        except Exception as exc:
            raise ToolConfigurationError(
                f"Failed to call MCP tool '{tool_name}' on server='{server_name}': {exc}"
            ) from exc
        return self._serialize_call_result(result)

    async def _list_tools_async(self, server: McpServerConfig) -> tuple[McpToolInfo, ...]:
        raw_tools = await self._client.get_tools(server_name=server.name)
        return tuple(self._tool_info_from_langchain_tool(tool) for tool in raw_tools)

    async def _call_tool_async(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        async with self._client.session(server_name) as session:
            return await session.call_tool(tool_name, arguments)

    def _serialize_call_result(self, result: Any) -> str:
        if hasattr(result, "model_dump"):
            payload = result.model_dump(mode="json", exclude_none=True)
        else:
            payload = result

        if isinstance(payload, dict):
            structured = payload.get("structuredContent")
            if structured is not None:
                return json.dumps(structured, ensure_ascii=False)

            content = payload.get("content")
            if isinstance(content, list):
                text_blocks = [
                    item.get("text")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
                ]
                if text_blocks:
                    return "\n".join(text_blocks)

        return json.dumps(payload, ensure_ascii=False)

    def _server_timeout(self, server: McpServerConfig) -> float:
        return server.timeout_seconds if server.timeout_seconds is not None else self._default_timeout_seconds

    def _build_connection(self, server: McpServerConfig) -> Connection:
        timeout_seconds = self._server_timeout(server)
        session_kwargs: dict[str, Any] = {"read_timeout_seconds": timedelta(seconds=timeout_seconds)}

        if server.transport == "stdio":
            if server.command is None:
                raise ToolConfigurationError(f"MCP stdio server '{server.name}' is missing command")
            connection: Connection = {
                "transport": "stdio",
                "command": server.command,
                "args": list(server.args),
                "session_kwargs": session_kwargs,
            }
            if server.env is not None:
                connection["env"] = server.env
            return connection

        if server.transport == "sse":
            if server.url is None:
                raise ToolConfigurationError(f"MCP sse server '{server.name}' is missing url")
            connection = {
                "transport": "sse",
                "url": server.url,
                "timeout": timeout_seconds,
                "sse_read_timeout": server.sse_read_timeout_seconds or max(timeout_seconds, 300.0),
                "session_kwargs": session_kwargs,
            }
            if server.headers is not None:
                connection["headers"] = server.headers
            return connection

        if server.transport == "streamable-http":
            if server.url is None:
                raise ToolConfigurationError(f"MCP streamable-http server '{server.name}' is missing url")
            connection = {
                "transport": "streamable_http",
                "url": server.url,
                "timeout": timedelta(seconds=timeout_seconds),
                "sse_read_timeout": timedelta(seconds=server.sse_read_timeout_seconds or max(timeout_seconds, 300.0)),
                "terminate_on_close": server.terminate_on_close,
                "session_kwargs": session_kwargs,
            }
            if server.headers is not None:
                connection["headers"] = server.headers
            return connection

        raise ToolConfigurationError(
            f"MCP server '{server.name}' uses unsupported transport '{server.transport}' in {self._manifest.path}. Supported: stdio, sse, streamable-http"
        )

    @staticmethod
    def _tool_info_from_langchain_tool(tool: Any) -> McpToolInfo:
        input_schema: dict[str, Any] = {}
        get_input_schema = getattr(tool, "get_input_schema", None)
        if callable(get_input_schema):
            try:
                schema = get_input_schema()
                if hasattr(schema, "model_json_schema"):
                    input_schema = schema.model_json_schema()
                elif isinstance(schema, dict):
                    input_schema = schema
            except Exception:
                input_schema = {}
        if not input_schema:
            args_schema = getattr(tool, "args_schema", None)
            if hasattr(args_schema, "model_json_schema"):
                input_schema = args_schema.model_json_schema()
        if not input_schema:
            tool_call_schema = getattr(tool, "tool_call_schema", None)
            if hasattr(tool_call_schema, "model_json_schema"):
                input_schema = tool_call_schema.model_json_schema()
            elif isinstance(tool_call_schema, dict):
                input_schema = tool_call_schema
        return McpToolInfo(
            name=str(getattr(tool, "name", "") or ""),
            description=str(getattr(tool, "description", "") or ""),
            input_schema=input_schema if isinstance(input_schema, dict) else {},
        )