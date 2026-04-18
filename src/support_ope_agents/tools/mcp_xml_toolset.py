from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.mcp_client import McpToolClient, McpToolInfo


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
class XmlMcpToolsetProvider:
    backend: McpToolClient

    @classmethod
    def from_config(cls, config: AppConfig) -> "XmlMcpToolsetProvider | None":
        client = McpToolClient.from_config(config) if config.tools.mcp_manifest_path is not None else None
        return cls(backend=client) if client is not None else None

    def list_tools(self, server_name: str) -> tuple[McpToolInfo, ...]:
        return self.backend.list_tools(server_name)

    def list_tool_names(self, server_name: str) -> set[str]:
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
            raise ValueError(f"selected MCP tool does not exist: {tool_name}. available_tools=[{tools_text}]")
        merged_arguments = {str(key): _normalize_scalar(value) for key, value in (static_arguments or {}).items()}
        merged_arguments.update({str(key): _normalize_scalar(value) for key, value in arguments.items()})
        return self.backend.call_tool(server_name, tool_name, merged_arguments)