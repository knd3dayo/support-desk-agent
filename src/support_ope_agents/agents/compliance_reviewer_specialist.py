from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_SPECIALIST, RESOLUTION_AGENT


def build_compliance_reviewer_specialist_definition() -> AgentDefinition:
    return AgentDefinition(
        COMPLIANCE_REVIEWER_SPECIALIST,
        "Review draft against policy",
        kind="specialist",
        parent_role=RESOLUTION_AGENT,
    )