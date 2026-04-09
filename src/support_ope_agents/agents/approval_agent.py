from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import APPROVAL_AGENT, SUPERVISOR_AGENT


def build_approval_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        APPROVAL_AGENT,
        "Manage human approval and reinvestigation decisions",
        kind="phase",
        parent_role=SUPERVISOR_AGENT,
    )