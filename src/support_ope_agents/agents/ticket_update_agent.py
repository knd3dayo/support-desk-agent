from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT, TICKET_UPDATE_AGENT


def build_ticket_update_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        TICKET_UPDATE_AGENT,
        "Write external ticket updates",
        kind="phase",
        parent_role=SUPERVISOR_AGENT,
    )