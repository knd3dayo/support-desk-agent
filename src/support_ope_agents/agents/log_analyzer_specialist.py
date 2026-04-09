from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATION_AGENT, LOG_ANALYZER_SPECIALIST


def build_log_analyzer_specialist_definition() -> AgentDefinition:
    return AgentDefinition(
        LOG_ANALYZER_SPECIALIST,
        "Analyze technical logs",
        kind="specialist",
        parent_role=INVESTIGATION_AGENT,
    )