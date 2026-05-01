from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_desk_agent.agents.abstract_agent import AbstractAgent
from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.agents.roles import APPROVAL_AGENT, SUPERVISOR_AGENT
from support_desk_agent.models.state_transitions import StateTransitionHelper

if TYPE_CHECKING:
    from support_desk_agent.models.state import CaseState


@dataclass(slots=True)
class ApprovalAgent(AbstractAgent):
    record_approval_decision_tool: Callable[..., Any]

    def wait_for_approval(self, state: CaseState) -> CaseState:
        return cast("CaseState", StateTransitionHelper.waiting_for_approval(state))

    def create_node(self):
        from support_desk_agent.models.state import CaseStateModel

        graph = StateGraph(CaseStateModel)
        graph.add_node("wait_for_approval", self.wait_for_approval)
        graph.add_edge(START, "wait_for_approval")
        graph.add_edge("wait_for_approval", END)
        return graph.compile()

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            APPROVAL_AGENT,
            "Request approval before sending updates or escalation drafts",
            kind="phase",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_approval_agent_definition() -> AgentDefinition:
        return ApprovalAgent.build_agent_definition()