from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import RESOLUTION_AGENT, SUPERVISOR_AGENT


def build_resolution_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        RESOLUTION_AGENT,
        "Synthesize findings and coordinate draft",
        kind="phase",
        parent_role=SUPERVISOR_AGENT,
    )