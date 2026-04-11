from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import OBJECTIVE_EVALUATION_AGENT, SUPERVISOR_AGENT


def build_objective_evaluation_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        OBJECTIVE_EVALUATION_AGENT,
        "Evaluate support handling objectively for report generation",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )