from __future__ import annotations

import argparse
import inspect
from dataclasses import dataclass
from typing import Any, Callable, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT, TICKET_UPDATE_AGENT
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.util.formatting import format_result


class SampleTicketUpdateState(TypedDict, total=False):
    status: str
    current_agent: str
    ticket_update_payload: str
    ticket_update_result: str
    next_action: str
    draft_response: str
    escalation_draft: str
    external_ticket_id: str
    internal_ticket_id: str
    approval_decision: str
    case_id: str
    workspace_path: str


@dataclass(slots=True)
class SampleTicketUpdateAgent(AbstractAgent):
    prepare_ticket_update_tool: Callable[..., Any] = staticmethod(lambda **_: "Zendesk / Redmine に反映する更新内容を準備しました。")
    zendesk_reply_tool: Callable[..., Any] = staticmethod(lambda **_: "zendesk update skipped")
    redmine_update_tool: Callable[..., Any] = staticmethod(lambda **_: "redmine update skipped")

    def _invoke_tool(self, tool: Callable[..., Any], **kwargs: object) -> str:
        try:
            result = tool(**kwargs)
        except TypeError:
            signature = inspect.signature(tool)
            filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
            result = tool(**filtered_kwargs)
        if inspect.isawaitable(result):
            return str(run_awaitable_sync(cast(Any, result)))
        return str(result)

    def prepare_update(self, state: dict[str, Any]) -> dict[str, Any]:
        draft_response = str(state.get("draft_response") or "").strip()
        escalation_draft = str(state.get("escalation_draft") or "").strip()
        prepared_payload = self._invoke_tool(
            self.prepare_ticket_update_tool,
            case_id=str(state.get("case_id") or "").strip(),
            workspace_path=str(state.get("workspace_path") or "").strip(),
            external_ticket_id=str(state.get("external_ticket_id") or "").strip(),
            internal_ticket_id=str(state.get("internal_ticket_id") or "").strip(),
            draft_response=draft_response,
            escalation_draft=escalation_draft,
            workflow_kind=str(state.get("workflow_kind") or "").strip(),
        ).strip()
        if escalation_draft:
            return StateTransitionHelper.ticket_update_prepared(
                state,
                payload=prepared_payload or f"Back support inquiry prepared: {escalation_draft}",
                next_action="問い合わせ文案を確定して外部連携を実行する",
            )
        if draft_response:
            return StateTransitionHelper.ticket_update_prepared(
                state,
                payload=prepared_payload or f"Customer reply prepared: {draft_response}",
                next_action="回答内容を確定してチケット更新を実行する",
            )
        return StateTransitionHelper.ticket_update_prepared(
            state,
            payload=prepared_payload or "Zendesk / Redmine に反映する更新内容を準備しました。",
            next_action=NextActionTexts.EXECUTE_TICKET_UPDATE,
        )

    def execute_update(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = str(state.get("ticket_update_payload") or "").strip()
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        external_ticket_id = str(state.get("external_ticket_id") or "").strip()
        internal_ticket_id = str(state.get("internal_ticket_id") or "").strip()
        approval_decision = str(state.get("approval_decision") or "").strip().lower()

        results: list[str] = []

        if internal_ticket_id:
            internal_result = self._invoke_tool(
                self.redmine_update_tool,
                case_id=case_id,
                workspace_path=workspace_path,
                ticket_id=internal_ticket_id,
                note=payload,
                payload=payload,
            )
            results.append(f"internal:{internal_result}")

        if external_ticket_id:
            if approval_decision in {"approved", "approve"}:
                external_result = self._invoke_tool(
                    self.zendesk_reply_tool,
                    case_id=case_id,
                    workspace_path=workspace_path,
                    ticket_id=external_ticket_id,
                    message=payload,
                    payload=payload,
                )
                results.append(f"external:{external_result}")
            else:
                results.append("external:skipped approval required")

        if not results:
            results.append("no ticket updates executed")

        return StateTransitionHelper.ticket_update_completed(state, result_message="; ".join(results))

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
        external_ticket_id: str = "",
        internal_ticket_id: str = "",
        approval_decision: str = "pending",
    ) -> dict[str, Any]:
        node = self.create_node()
        return dict(
            node.invoke(
                {
                    "draft_response": draft_response,
                    "escalation_draft": escalation_draft,
                    "external_ticket_id": external_ticket_id,
                    "internal_ticket_id": internal_ticket_id,
                    "approval_decision": approval_decision,
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