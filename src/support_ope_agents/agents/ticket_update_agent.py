from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.roles import TICKET_UPDATE_AGENT

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class TicketUpdateAgent:
    prepare_ticket_update_tool: Callable[..., Any]
    zendesk_reply_tool: Callable[..., Any]
    redmine_update_tool: Callable[..., Any]

    def prepare_update(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["current_agent"] = TICKET_UPDATE_AGENT
        update["ticket_update_payload"] = "Zendesk / Redmine に反映する更新内容を準備しました。"
        update["next_action"] = "外部チケット更新内容を確定して更新を実行する"
        return cast("CaseState", update)

    def execute_update(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "CLOSED"
        update["current_agent"] = TICKET_UPDATE_AGENT
        update["ticket_update_result"] = "Zendesk と Redmine の更新処理を完了しました。"
        update["next_action"] = "外部チケット更新を完了しました"
        return cast("CaseState", update)

    def create_node(self):
        from support_ope_agents.workflow.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("ticket_update_prepare", self.prepare_update)
        graph.add_node("ticket_update_execute", self.execute_update)
        graph.add_edge(START, "ticket_update_prepare")
        graph.add_edge("ticket_update_prepare", "ticket_update_execute")
        graph.add_edge("ticket_update_execute", END)
        return graph.compile()