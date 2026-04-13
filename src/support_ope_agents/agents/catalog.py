from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.back_support_inquiry_writer_agent import BackSupportInquiryWriterPhaseExecutor
from support_ope_agents.agents.compliance_reviewer_agent import ComplianceReviewerPhaseExecutor
from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.agents.intake_agent import IntakeAgent
from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor
from support_ope_agents.agents.objective_evaluation_agent import ObjectiveEvaluationAgent
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor


def build_default_agent_definitions() -> list[AgentDefinition]:
    return [
        SupervisorPhaseExecutor.build_supervisor_agent_definition(),
        ObjectiveEvaluationAgent.build_objective_evaluation_agent_definition(),
        IntakeAgent.build_intake_agent_definition(),
        LogAnalyzerPhaseExecutor.build_log_analyzer_agent_definition(),
        KnowledgeRetrieverPhaseExecutor.build_knowledge_retriever_agent_definition(),
        DraftWriterPhaseExecutor.build_draft_writer_agent_definition(),
        ComplianceReviewerPhaseExecutor.build_compliance_reviewer_agent_definition(),
        DraftWriterPhaseExecutor.build_draft_writer_agent_definition(),
        BackSupportInquiryWriterPhaseExecutor.build_back_support_inquiry_writer_agent_definition(),
    ]