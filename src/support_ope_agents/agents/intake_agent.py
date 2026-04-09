from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT


def build_intake_agent_definition() -> AgentDefinition:
    return AgentDefinition(INTAKE_AGENT, "Triage and initialize the case", kind="phase", parent_role=SUPERVISOR_AGENT)