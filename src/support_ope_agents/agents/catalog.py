from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.back_support_inquiry_writer_agent import BackSupportInquiryWriterPhaseExecutor
from support_ope_agents.agents.investigate_agent import InvestigateAgent
from support_ope_agents.agents.intake_agent import IntakeAgent
from support_ope_agents.agents.objective_evaluation_agent import ObjectiveEvaluationAgent
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor


def build_default_agent_definitions() -> list[AgentDefinition]:
    return [
        SupervisorPhaseExecutor.build_supervisor_agent_definition(),
        ObjectiveEvaluationAgent.build_objective_evaluation_agent_definition(),
        IntakeAgent.build_intake_agent_definition(),
        InvestigateAgent.build_investigate_agent_definition(),
        BackSupportInquiryWriterPhaseExecutor.build_back_support_inquiry_writer_agent_definition(),
    ]