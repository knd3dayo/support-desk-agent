from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.session_group import SseServerParameters, StreamableHttpParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from support_ope_agents.config.models import AppConfig, McpToolBinding


class ToolConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    name: str
    transport: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, Any] | None = None
    timeout_seconds: float | None = None
    sse_read_timeout_seconds: float | None = None
    terminate_on_close: bool = True


def _expand_string(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value))


def _normalize_string_map(raw: dict[str, Any] | None) -> dict[str, str] | None:
    if raw is None:
        return None
    return {str(key): _expand_string(str(value)) for key, value in raw.items()}


class McpManifest:
    def __init__(self, path: Path, servers: dict[str, McpServerConfig]):
        self.path = path
        self.servers = servers

    @classmethod
    def load(cls, path: Path) -> "McpManifest":
        if not path.exists():
            raise ToolConfigurationError(f"MCP manifest was not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        raw_servers = raw.get("mcpServers")
        if not isinstance(raw_servers, dict):
            raise ToolConfigurationError(f"MCP manifest must contain 'mcpServers': {path}")

        servers: dict[str, McpServerConfig] = {}
        for name, definition in raw_servers.items():
            if not isinstance(definition, dict):
                raise ToolConfigurationError(f"MCP server '{name}' definition must be an object in {path}")
            if definition.get("disabled") is True:
                continue

            transport = str(definition.get("type") or ("stdio" if definition.get("command") else "")).strip()
            if not transport:
                raise ToolConfigurationError(f"MCP server '{name}' is missing transport type in {path}")

            servers[name] = cls._build_server_config(path, name, transport, definition)

        return cls(path=path, servers=servers)

    @staticmethod
    def _build_server_config(path: Path, name: str, transport: str, definition: dict[str, Any]) -> McpServerConfig:
        timeout = definition.get("timeout")
        sse_timeout = definition.get("sse_read_timeout")

        if transport == "stdio":
            command = definition.get("command")
            if not command:
                raise ToolConfigurationError(f"MCP stdio server '{name}' is missing 'command' in {path}")
            args = tuple(_expand_string(str(item)) for item in definition.get("args", []))
            return McpServerConfig(
                name=name,
                transport=transport,
                command=_expand_string(str(command)),
                args=args,
                env=_normalize_string_map(definition.get("env")),
                timeout_seconds=float(timeout) if timeout is not None else None,
            )

        if transport in {"sse", "streamable-http"}:
            url = definition.get("url")
            if not url:
                raise ToolConfigurationError(f"MCP server '{name}' is missing 'url' in {path}")
            return McpServerConfig(
                name=name,
                transport=transport,
                url=_expand_string(str(url)),
                headers=definition.get("headers"),
                timeout_seconds=float(timeout) if timeout is not None else None,
                sse_read_timeout_seconds=float(sse_timeout) if sse_timeout is not None else None,
                terminate_on_close=bool(definition.get("terminate_on_close", True)),
            )

        raise ToolConfigurationError(
            f"MCP server '{name}' uses unsupported transport '{transport}' in {path}. Supported: stdio, sse, streamable-http"
        )


class McpToolOverrideResolver:
    def __init__(self, manifest: McpManifest, default_timeout_seconds: float = 30.0):
        self._manifest = manifest
        self._default_timeout_seconds = default_timeout_seconds
        self._tool_name_cache: dict[str, set[str]] = {}

    @classmethod
    def from_config(cls, config: AppConfig) -> "McpToolOverrideResolver":
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

    def list_tool_names(self, server_name: str) -> set[str]:
        if server_name in self._tool_name_cache:
            return self._tool_name_cache[server_name]

        server = self._manifest.servers[server_name]
        try:
            names = anyio.run(self._list_tool_names_async, server)
        except Exception as exc:
            raise ToolConfigurationError(
                f"Failed to query MCP server '{server_name}' from manifest={self._manifest.path}: {exc}"
            ) from exc

        self._tool_name_cache[server_name] = names
        return names

    async def _list_tool_names_async(self, server: McpServerConfig) -> set[str]:
        async with self._session_for(server) as session:
            result = await session.list_tools()
        return {tool.name for tool in result.tools}

    async def _call_tool_async(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        server = self._manifest.servers[server_name]
        async with self._session_for(server) as session:
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

    @asynccontextmanager
    async def _session_for(self, server: McpServerConfig):
        timeout_seconds = self._server_timeout(server)
        if server.transport == "stdio":
            assert server.command is not None
            params = StdioServerParameters(command=server.command, args=list(server.args), env=server.env)
            async with stdio_client(params) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=timeout_seconds)) as session:
                    await session.initialize()
                    yield session
            return

        if server.transport == "sse":
            assert server.url is not None
            params = SseServerParameters(
                url=server.url,
                headers=server.headers,
                timeout=timeout_seconds,
                sse_read_timeout=server.sse_read_timeout_seconds or max(timeout_seconds, 300.0),
            )
            async with sse_client(
                url=params.url,
                headers=params.headers,
                timeout=params.timeout,
                sse_read_timeout=params.sse_read_timeout,
            ) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=timeout_seconds)) as session:
                    await session.initialize()
                    yield session
            return

        assert server.url is not None
        params = StreamableHttpParameters(
            url=server.url,
            headers=server.headers,
            timeout=timedelta(seconds=timeout_seconds),
            sse_read_timeout=timedelta(seconds=server.sse_read_timeout_seconds or max(timeout_seconds, 300.0)),
            terminate_on_close=server.terminate_on_close,
        )
        httpx_client = create_mcp_http_client(
            headers=params.headers,
            timeout=httpx.Timeout(timeout_seconds, read=params.sse_read_timeout.total_seconds()),
        )
        async with httpx_client:
            async with streamable_http_client(
                url=params.url,
                http_client=httpx_client,
                terminate_on_close=params.terminate_on_close,
            ) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=timeout_seconds),
                ) as session:
                    await session.initialize()
                    yield session