from __future__ import annotations

from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.mcp_client import McpToolClient


def validate_ticket_sources_startup(config: AppConfig, mcp_tool_client: McpToolClient | None) -> None:
    if mcp_tool_client is None:
        return

    ticket_sources = config.tools.ticket_sources
    for ticket_kind, binding in (("external", ticket_sources.external), ("internal", ticket_sources.internal)):
        if not binding.enabled:
            continue
        mcp_tool_client.validate_ticket_source(ticket_kind=ticket_kind, server_name=binding.server)