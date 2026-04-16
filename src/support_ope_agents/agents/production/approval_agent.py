from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.roles import APPROVAL_AGENT

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class ApprovalAgent:
    record_approval_decision_tool: Callable[..., Any]

    def wait_for_approval(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "WAITING_APPROVAL"
        update["current_agent"] = APPROVAL_AGENT
        update.setdefault("approval_decision", "pending")
        if update.get("execution_mode") == "plan":
            update["next_action"] = "この計画で action を実行するか確認してください。"
        elif update.get("escalation_required"):
            update["next_action"] = "エスカレーション問い合わせ文案を確認し、送付可否を承認してください。"
        else:
            update["next_action"] = "回答ドラフトを確認し、チケット更新を承認してください。"
        return cast("CaseState", update)

    def create_node(self):
        from support_ope_agents.workflow.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("wait_for_approval", self.wait_for_approval)
        graph.add_edge(START, "wait_for_approval")
        graph.add_edge("wait_for_approval", END)
        return graph.compile()