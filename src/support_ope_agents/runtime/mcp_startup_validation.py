from __future__ import annotations

from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.mcp_client import McpToolClient


def validate_ticket_sources_startup(config: AppConfig, mcp_tool_client: McpToolClient | None) -> None:
    if mcp_tool_client is None:
        return

    for ticket_kind in ("external", "internal"):
        logical_tool = config.tools.get_logical_tool(f"{ticket_kind}_ticket")
        if logical_tool is None or not logical_tool.enabled or logical_tool.provider != "mcp":
            continue
        mcp_tool_client.validate_ticket_source(ticket_kind=ticket_kind, server_name=str(logical_tool.server or ""))