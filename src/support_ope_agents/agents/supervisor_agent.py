from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT


def build_supervisor_agent_definition() -> AgentDefinition:
    return AgentDefinition(SUPERVISOR_AGENT, "Supervise the full support workflow", kind="supervisor")