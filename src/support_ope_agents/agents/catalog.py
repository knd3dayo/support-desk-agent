from __future__ import annotations

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.production.investigate_agent import InvestigateAgent
from support_ope_agents.agents.production.intake_agent import IntakeAgent
from support_ope_agents.agents.objective_evaluator import ObjectiveEvaluator
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor


def build_default_agent_definitions() -> list[AgentDefinition]:
    return [
        SupervisorPhaseExecutor.build_supervisor_agent_definition(),
        ObjectiveEvaluator.build_objective_evaluator_definition(),
        IntakeAgent.build_intake_agent_definition(),
        InvestigateAgent.build_investigate_agent_definition(),
    ]