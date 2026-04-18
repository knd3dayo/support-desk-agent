from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT, TICKET_UPDATE_AGENT
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper

if TYPE_CHECKING:
    from support_ope_agents.models.state import CaseState


@dataclass(slots=True)
class TicketUpdateAgent(AbstractAgent):
    prepare_ticket_update_tool: Callable[..., Any]
    zendesk_reply_tool: Callable[..., Any]
    redmine_update_tool: Callable[..., Any]

    def prepare_update(self, state: CaseState) -> CaseState:
        return cast(
            "CaseState",
            StateTransitionHelper.ticket_update_prepared(
                state,
                payload="Zendesk / Redmine に反映する更新内容を準備しました。",
                next_action=NextActionTexts.EXECUTE_TICKET_UPDATE,
            ),
        )

    def execute_update(self, state: CaseState) -> CaseState:
        return cast("CaseState", StateTransitionHelper.ticket_update_completed(state))

    def create_node(self):
        from support_ope_agents.models.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("ticket_update_prepare", self.prepare_update)
        graph.add_node("ticket_update_execute", self.execute_update)
        graph.add_edge(START, "ticket_update_prepare")
        graph.add_edge("ticket_update_prepare", "ticket_update_execute")
        graph.add_edge("ticket_update_execute", END)
        return graph.compile()

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            TICKET_UPDATE_AGENT,
            "Prepare and execute ticket updates after approval",
            kind="phase",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_ticket_update_agent_definition() -> AgentDefinition:
        return TicketUpdateAgent.build_agent_definition()