from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import DRAFT_WRITER_AGENT, RESOLUTION_AGENT


def build_draft_writer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        DRAFT_WRITER_AGENT,
        "Write customer-facing draft response",
        kind="agent",
        parent_role=RESOLUTION_AGENT,
    )