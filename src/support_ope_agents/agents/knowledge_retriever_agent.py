from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT, SUPERVISOR_AGENT


def build_knowledge_retriever_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        KNOWLEDGE_RETRIEVER_AGENT,
        "Search knowledge sources",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )