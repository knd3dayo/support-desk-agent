from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT, TICKET_UPDATE_AGENT
from support_ope_agents.util.formatting import format_result


class SampleTicketUpdateState(TypedDict, total=False):
    status: str
    current_agent: str
    ticket_update_payload: str
    ticket_update_result: str
    next_action: str
    draft_response: str
    escalation_draft: str


@dataclass(slots=True)
class SampleTicketUpdateAgent(AbstractAgent):
    def prepare_update(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        update["current_agent"] = TICKET_UPDATE_AGENT
        draft_response = str(update.get("draft_response") or "").strip()
        escalation_draft = str(update.get("escalation_draft") or "").strip()
        if escalation_draft:
            update["ticket_update_payload"] = f"Back support inquiry prepared: {escalation_draft}"
            update["next_action"] = "問い合わせ文案を確定して外部連携を実行する"
        elif draft_response:
            update["ticket_update_payload"] = f"Customer reply prepared: {draft_response}"
            update["next_action"] = "回答内容を確定してチケット更新を実行する"
        else:
            update["ticket_update_payload"] = "Zendesk / Redmine に反映する更新内容を準備しました。"
            update["next_action"] = "外部チケット更新内容を確定して更新を実行する"
        return update

    def execute_update(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        update["status"] = "CLOSED"
        update["current_agent"] = TICKET_UPDATE_AGENT
        update["ticket_update_result"] = "Zendesk と Redmine の更新処理を完了しました。"
        update["next_action"] = "外部チケット更新を完了しました"
        return update

    def create_node(self) -> Any:
        graph = StateGraph(SampleTicketUpdateState)
        graph.add_node(
            "ticket_update_prepare",
            lambda state: cast(SampleTicketUpdateState, self.prepare_update(cast(dict[str, Any], state))),
        )
        graph.add_node(
            "ticket_update_execute",
            lambda state: cast(SampleTicketUpdateState, self.execute_update(cast(dict[str, Any], state))),
        )
        graph.add_edge(START, "ticket_update_prepare")
        graph.add_edge("ticket_update_prepare", "ticket_update_execute")
        graph.add_edge("ticket_update_execute", END)
        return graph.compile()

    def execute(
        self,
        *,
        draft_response: str = "",
        escalation_draft: str = "",
    ) -> dict[str, Any]:
        node = self.create_node()
        return dict(
            node.invoke(
                {
                    "draft_response": draft_response,
                    "escalation_draft": escalation_draft,
                }
            )
        )

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
        return SampleTicketUpdateAgent.build_agent_definition()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample ticket update agent")
    parser.add_argument("--draft-response", default="", help="Draft reply to reflect in the outgoing ticket update")
    parser.add_argument("--escalation-draft", default="", help="Escalation draft to reflect in the outgoing ticket update")
    args = parser.parse_args()

    agent = SampleTicketUpdateAgent()
    result = agent.execute(
        draft_response=args.draft_response,
        escalation_draft=args.escalation_draft,
    )
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())