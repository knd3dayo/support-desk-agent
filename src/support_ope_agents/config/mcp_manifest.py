from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class McpConfigError(ValueError):
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


def _resolve_env_value(value: str, *, path: Path, server_name: str, env_key: str) -> str:
    prefix = "os.environ/"
    if not value.startswith(prefix):
        return _expand_string(value)

    env_name = value.removeprefix(prefix).strip()
    if not env_name:
        raise McpConfigError(
            f"MCP server '{server_name}' has invalid env reference for '{env_key}' in {path}: empty env var name"
        )

    resolved = os.getenv(env_name)
    if resolved is None or resolved == "":
        raise McpConfigError(
            f"MCP server '{server_name}' references unset env var '{env_name}' for '{env_key}' in {path}"
        )
    return resolved


def _normalize_env_map(path: Path, server_name: str, raw: dict[str, Any] | None) -> dict[str, str] | None:
    if raw is None:
        return None
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise McpConfigError(f"MCP server '{server_name}' has invalid env key in {path}: {key!r}")
        if not isinstance(value, str):
            raise McpConfigError(
                f"MCP server '{server_name}' env '{key}' must be a string in {path}: {value!r}"
            )
        normalized[key] = _resolve_env_value(value, path=path, server_name=server_name, env_key=key)
    return normalized


@dataclass(frozen=True, slots=True)
class McpManifest:
    path: Path
    servers: dict[str, McpServerConfig]

    @classmethod
    def load(cls, path: Path) -> "McpManifest":
        if not path.exists():
            raise McpConfigError(f"MCP manifest was not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        raw_servers = raw.get("mcpServers")
        if not isinstance(raw_servers, dict):
            raise McpConfigError(f"MCP manifest must contain 'mcpServers': {path}")

        servers: dict[str, McpServerConfig] = {}
        for name, definition in raw_servers.items():
            if not isinstance(definition, dict):
                raise McpConfigError(f"MCP server '{name}' definition must be an object in {path}")
            if definition.get("disabled") is True:
                continue

            transport = str(
                definition.get("transport") or definition.get("type") or ("stdio" if definition.get("command") else "")
            ).strip()
            if not transport:
                raise McpConfigError(f"MCP server '{name}' is missing transport type in {path}")

            servers[name] = cls._build_server_config(path, name, transport, definition)

        return cls(path=path, servers=servers)

    @staticmethod
    def _build_server_config(path: Path, name: str, transport: str, definition: dict[str, Any]) -> McpServerConfig:
        timeout = definition.get("timeout")
        sse_timeout = definition.get("sse_read_timeout")

        if transport == "stdio":
            command = definition.get("command")
            if not command:
                raise McpConfigError(f"MCP stdio server '{name}' is missing 'command' in {path}")
            args = tuple(_expand_string(str(item)) for item in definition.get("args", []))
            env = definition.get("env")
            if env is not None and not isinstance(env, dict):
                raise McpConfigError(f"MCP server '{name}' field 'env' must be an object in {path}")
            return McpServerConfig(
                name=name,
                transport=transport,
                command=_expand_string(str(command)),
                args=args,
                env=_normalize_env_map(path, name, env),
                timeout_seconds=float(timeout) if timeout is not None else None,
            )

        if transport in {"sse", "streamable-http"}:
            url = definition.get("url")
            if not url:
                raise McpConfigError(f"MCP server '{name}' is missing 'url' in {path}")
            return McpServerConfig(
                name=name,
                transport=transport,
                url=_expand_string(str(url)),
                headers=definition.get("headers"),
                timeout_seconds=float(timeout) if timeout is not None else None,
                sse_read_timeout_seconds=float(sse_timeout) if sse_timeout is not None else None,
                terminate_on_close=bool(definition.get("terminate_on_close", True)),
            )

        raise McpConfigError(
            f"MCP server '{name}' uses unsupported transport '{transport}' in {path}. Supported: stdio, sse, streamable-http"
        )