from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import LOG_ANALYZER_AGENT, SUPERVISOR_AGENT


def build_log_analyzer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        LOG_ANALYZER_AGENT,
        "Analyze technical logs",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )