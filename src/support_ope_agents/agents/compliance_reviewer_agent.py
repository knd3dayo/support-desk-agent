from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT, RESOLUTION_AGENT


def build_compliance_reviewer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        COMPLIANCE_REVIEWER_AGENT,
        "Review draft against policy",
        kind="agent",
        parent_role=RESOLUTION_AGENT,
    )