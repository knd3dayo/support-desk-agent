from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATION_AGENT, KNOWLEDGE_RETRIEVER_SPECIALIST


def build_knowledge_retriever_specialist_definition() -> AgentDefinition:
    return AgentDefinition(
        KNOWLEDGE_RETRIEVER_SPECIALIST,
        "Search knowledge sources",
        kind="specialist",
        parent_role=INVESTIGATION_AGENT,
    )