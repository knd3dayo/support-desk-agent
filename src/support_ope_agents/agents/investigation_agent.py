from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATION_AGENT, SUPERVISOR_AGENT


def build_investigation_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        INVESTIGATION_AGENT,
        "Plan investigation and orchestrate specialists",
        kind="phase",
        parent_role=SUPERVISOR_AGENT,
    )