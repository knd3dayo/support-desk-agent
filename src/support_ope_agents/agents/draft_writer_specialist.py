from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import DRAFT_WRITER_SPECIALIST, RESOLUTION_AGENT


def build_draft_writer_specialist_definition() -> AgentDefinition:
    return AgentDefinition(
        DRAFT_WRITER_SPECIALIST,
        "Write customer-facing draft response",
        kind="specialist",
        parent_role=RESOLUTION_AGENT,
    )