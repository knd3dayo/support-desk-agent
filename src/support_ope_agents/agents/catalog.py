from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.approval_agent import build_approval_agent_definition
from support_ope_agents.agents.compliance_reviewer_specialist import build_compliance_reviewer_specialist_definition
from support_ope_agents.agents.draft_writer_specialist import build_draft_writer_specialist_definition
from support_ope_agents.agents.intake_agent import build_intake_agent_definition
from support_ope_agents.agents.investigation_agent import build_investigation_agent_definition
from support_ope_agents.agents.knowledge_retriever_specialist import build_knowledge_retriever_specialist_definition
from support_ope_agents.agents.log_analyzer_specialist import build_log_analyzer_specialist_definition
from support_ope_agents.agents.resolution_agent import build_resolution_agent_definition
from support_ope_agents.agents.supervisor_agent import build_supervisor_agent_definition
from support_ope_agents.agents.ticket_update_agent import build_ticket_update_agent_definition


def build_default_agent_definitions() -> list[AgentDefinition]:
    return [
        build_supervisor_agent_definition(),
        build_intake_agent_definition(),
        build_investigation_agent_definition(),
        build_log_analyzer_specialist_definition(),
        build_knowledge_retriever_specialist_definition(),
        build_resolution_agent_definition(),
        build_draft_writer_specialist_definition(),
        build_compliance_reviewer_specialist_definition(),
        build_approval_agent_definition(),
        build_ticket_update_agent_definition(),
    ]