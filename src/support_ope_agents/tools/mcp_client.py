from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from xml.sax.saxutils import escape

import anyio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection
from langchain_core.tools import BaseTool
from langchain_core.tools import StructuredTool

from support_ope_agents.config import AppConfig, McpConfigError, McpManifest, McpServerConfig, McpToolBinding

ToolConfigurationError = McpConfigError


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_scalar(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_scalar(item) for key, item in value.items()}
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        if stripped.lower() == "true":
            return True
        if stripped.lower() == "false":
            return False
        return stripped
    return value


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
        self._langchain_tool_cache: dict[str, tuple[BaseTool, ...]] = {}
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

    @staticmethod
    def _is_server_only_ticket_binding(*, logical_tool_name: str, binding: McpToolBinding) -> bool:
        return logical_tool_name in {"external_ticket", "internal_ticket"} and not str(binding.tool or "").strip()

    def validate_logical_tool(self, *, logical_tool_name: str, binding: McpToolBinding) -> None:
        if self._is_server_only_ticket_binding(logical_tool_name=logical_tool_name, binding=binding):
            ticket_kind = logical_tool_name.removesuffix("_ticket")
            self.validate_ticket_source(ticket_kind=ticket_kind, server_name=binding.server)
            return
        self.validate_binding(role="tools.logical_tools", logical_tool_name=logical_tool_name, binding=binding)

    def validate_ticket_source(self, *, ticket_kind: str, server_name: str) -> None:
        logical_tool_name = f"{ticket_kind}_ticket"
        if server_name not in self._manifest.servers:
            available = ", ".join(sorted(self._manifest.servers)) or "<none>"
            raise ToolConfigurationError(
                f"tools.logical_tools.{logical_tool_name} references unknown MCP server '{server_name}'. "
                f"manifest={self._manifest.path} available_servers=[{available}]"
            )
        try:
            self.list_tools(server_name)
        except ToolConfigurationError as exc:
            raise ToolConfigurationError(
                f"tools.logical_tools.{logical_tool_name} failed startup MCP connectivity check for server '{server_name}': {exc}"
            ) from exc

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

        tools = tuple(self._tool_info_from_langchain_tool(tool) for tool in self.get_langchain_tools(server_name))
        self._tool_cache[server_name] = tools
        self._tool_name_cache[server_name] = {tool.name for tool in tools}
        return tools

    def get_langchain_tools(self, server_name: str) -> tuple[BaseTool, ...]:
        if server_name in self._langchain_tool_cache:
            return self._langchain_tool_cache[server_name]

        if server_name not in self._manifest.servers:
            available = ", ".join(sorted(self._manifest.servers)) or "<none>"
            raise ToolConfigurationError(
                f"unknown MCP server '{server_name}'. manifest={self._manifest.path} available_servers=[{available}]"
            )

        server = self._manifest.servers[server_name]
        try:
            tools = anyio.run(self._get_langchain_tools_async, server)
        except Exception as exc:
            raise ToolConfigurationError(
                f"Failed to query MCP server '{server_name}' from manifest={self._manifest.path}: {exc}"
            ) from exc

        self._langchain_tool_cache[server_name] = tools
        return tools

    def get_agent_tools(
        self,
        server_name: str,
        *,
        static_arguments: dict[str, Any] | None = None,
        on_tool_call: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[BaseTool, ...]:
        wrapped_tools: list[BaseTool] = []
        for tool in self.get_langchain_tools(server_name):
            args_schema = getattr(tool, "args_schema", None)

            def _call_tool(*, _tool: BaseTool = tool, **kwargs: Any) -> str:
                filtered_arguments = {key: value for key, value in kwargs.items() if value is not None}
                serialized_result = self.call_tool(
                    server_name,
                    _tool.name,
                    filtered_arguments,
                    static_arguments=static_arguments,
                )
                if on_tool_call is not None:
                    on_tool_call(
                        {
                            "tool_name": _tool.name,
                            "arguments": filtered_arguments,
                            "raw_result": serialized_result,
                        }
                    )
                return serialized_result

            tool_kwargs: dict[str, Any] = {
                "func": _call_tool,
                "name": tool.name,
                "description": getattr(tool, "description", tool.name) or tool.name,
            }
            if args_schema is not None:
                tool_kwargs["args_schema"] = args_schema
                tool_kwargs["infer_schema"] = False
            wrapped_tools.append(StructuredTool.from_function(**tool_kwargs))
        return tuple(wrapped_tools)

    def list_tool_names(self, server_name: str) -> set[str]:
        if server_name in self._tool_name_cache:
            return self._tool_name_cache[server_name]
        return {tool.name for tool in self.list_tools(server_name)}

    def render_tools_xml(self, server_name: str) -> str:
        parts = [f'<tools server="{escape(server_name)}">']
        for tool in self.list_tools(server_name):
            input_schema = json.dumps(tool.input_schema, ensure_ascii=False, sort_keys=True)
            parts.extend(
                [
                    "  <tool>",
                    f"    <name>{escape(tool.name)}</name>",
                    f"    <description>{escape(tool.description)}</description>",
                    f"    <input_schema>{escape(input_schema)}</input_schema>",
                    "  </tool>",
                ]
            )
        parts.append("</tools>")
        return "\n".join(parts)

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        static_arguments: dict[str, Any] | None = None,
    ) -> str:
        available_tools = self.list_tool_names(server_name)
        if tool_name not in available_tools:
            tools_text = ", ".join(sorted(available_tools)) or "<none>"
            raise ToolConfigurationError(
                f"unknown MCP tool '{tool_name}' for server='{server_name}'. available_tools=[{tools_text}]"
            )
        merged_arguments = {str(key): _normalize_scalar(value) for key, value in (static_arguments or {}).items()}
        merged_arguments.update({str(key): _normalize_scalar(value) for key, value in arguments.items()})
        try:
            result = anyio.run(self._call_tool_async, server_name, tool_name, merged_arguments)
        except Exception as exc:
            raise ToolConfigurationError(
                f"Failed to call MCP tool '{tool_name}' on server='{server_name}': {exc}"
            ) from exc
        return self._serialize_call_result(result)

    async def _get_langchain_tools_async(self, server: McpServerConfig) -> tuple[BaseTool, ...]:
        return tuple(await self._client.get_tools(server_name=server.name))

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
                text_blocks: list[str] = []
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "text":
                        continue
                    text = item.get("text")
                    if isinstance(text, str):
                        text_blocks.append(text)
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
                model_json_schema = getattr(schema, "model_json_schema", None)
                if callable(model_json_schema):
                    schema_payload = model_json_schema()
                    if isinstance(schema_payload, dict):
                        input_schema = schema_payload
                elif isinstance(schema, dict):
                    input_schema = schema
            except Exception:
                input_schema = {}
        if not input_schema:
            args_schema = getattr(tool, "args_schema", None)
            model_json_schema = getattr(args_schema, "model_json_schema", None)
            if callable(model_json_schema):
                schema_payload = model_json_schema()
                if isinstance(schema_payload, dict):
                    input_schema = schema_payload
        if not input_schema:
            tool_call_schema = getattr(tool, "tool_call_schema", None)
            model_json_schema = getattr(tool_call_schema, "model_json_schema", None)
            if callable(model_json_schema):
                schema_payload = model_json_schema()
                if isinstance(schema_payload, dict):
                    input_schema = schema_payload
            elif isinstance(tool_call_schema, dict):
                input_schema = tool_call_schema
        return McpToolInfo(
            name=str(getattr(tool, "name", "") or ""),
            description=str(getattr(tool, "description", "") or ""),
            input_schema=input_schema if isinstance(input_schema, dict) else {},
        )