from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.intake_agent import IntakePhaseExecutor
from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    INTAKE_AGENT,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
)
from support_ope_agents.workflow.state import CaseState


def build_case_workflow(*, checkpointer: Any | None = None, intake_executor: IntakePhaseExecutor | None = None):
    graph = StateGraph(CaseState)
    graph.add_node("receive_case", _receive_case)
    graph.add_node("intake", _build_intake_node(intake_executor))
    graph.add_node("investigation", _investigation)
    graph.add_node("draft_review", _draft_review)
    graph.add_node("wait_for_approval", _wait_for_approval)
    _add_ticket_update_subgraph(graph)

    graph.add_edge(START, "receive_case")
    graph.add_edge("receive_case", "intake")
    graph.add_edge("intake", "investigation")
    graph.add_edge("investigation", "draft_review")
    graph.add_edge("draft_review", "wait_for_approval")
    graph.add_conditional_edges(
        "wait_for_approval",
        _route_after_approval,
        {
            "ticket_update_prepare": "ticket_update_prepare",
            "draft_review": "draft_review",
            "investigation": "investigation",
            "__end__": END,
        },
    )
    graph.add_edge("ticket_update_execute", END)
    return graph.compile(checkpointer=checkpointer) if checkpointer is not None else graph.compile()


def _add_ticket_update_subgraph(graph: StateGraph[CaseState]) -> None:
    graph.add_node("ticket_update_prepare", _ticket_update_prepare)
    graph.add_node("ticket_update_execute", _ticket_update_execute)
    graph.add_edge("ticket_update_prepare", "ticket_update_execute")


def _receive_case(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "RECEIVED"
    update.setdefault("current_agent", SUPERVISOR_AGENT)
    update.setdefault("created_at", datetime.now(UTC).isoformat())
    update.setdefault("approval_history", [])
    update.setdefault("agent_errors", [])
    update.setdefault("context_usage", {})
    update.setdefault("plan_steps", [])
    update.setdefault("plan_summary", "")
    return cast(CaseState, update)


def _build_intake_node(intake_executor: IntakePhaseExecutor | None):
    executor = intake_executor or _NoOpIntakeExecutor()

    def _intake(state: CaseState) -> CaseState:
        return cast(CaseState, executor.execute(state))

    return _intake


class _NoOpIntakeExecutor:
    def execute(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "TRIAGED"
        update["current_agent"] = INTAKE_AGENT
        if update.get("execution_mode") == "plan":
            update["next_action"] = "ユーザーに計画を提示して承認を得る"
        else:
            update["next_action"] = "SuperVisorAgent が調査フェーズを開始する"
        return cast(CaseState, update)


def _investigation(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "INVESTIGATING"
    update["current_agent"] = SUPERVISOR_AGENT
    if update.get("execution_mode") == "action":
        update["investigation_summary"] = str(update.get("investigation_summary") or "SuperVisorAgent 配下でログ解析とナレッジ探索を開始する準備が整っています。")
    return cast(CaseState, update)


def _draft_review(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "DRAFT_READY"
    update["current_agent"] = SUPERVISOR_AGENT
    if update.get("execution_mode") == "plan":
        update["draft_response"] = "plan モードでは SuperVisorAgent がドラフト作成とレビュー方針のみを返却し、action モードで実際の生成へ進みます。"
    else:
        update.setdefault("draft_response", "action モードで SuperVisorAgent 配下のドラフト作成とレビューを開始する準備が整っています。")
    return cast(CaseState, update)


def _wait_for_approval(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "WAITING_APPROVAL"
    update["current_agent"] = APPROVAL_AGENT
    update.setdefault("approval_decision", "pending")
    if update.get("execution_mode") == "plan":
        update["next_action"] = "この計画で action を実行するか確認してください。"
    else:
        update["next_action"] = "回答ドラフトを確認し、チケット更新を承認してください。"
    return cast(CaseState, update)


def _ticket_update_prepare(state: CaseState) -> CaseState:
    update = dict(state)
    update["current_agent"] = TICKET_UPDATE_AGENT
    update["ticket_update_payload"] = "Zendesk / Redmine に反映する更新内容を準備しました。"
    update["next_action"] = "外部チケット更新内容を確定して更新を実行する"
    return cast(CaseState, update)


def _ticket_update_execute(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "CLOSED"
    update["current_agent"] = TICKET_UPDATE_AGENT
    update["ticket_update_result"] = "Zendesk と Redmine の更新処理を完了しました。"
    update["next_action"] = "外部チケット更新を完了しました"
    return cast(CaseState, update)


def _route_after_approval(state: CaseState) -> str:
    decision = str(state.get("approval_decision", "pending")).lower()
    if decision in {"approved", "approve"}:
        return "ticket_update_prepare"
    if decision in {"rejected", "reject"}:
        return "draft_review"
    if decision == "reinvestigate":
        return "investigation"
    return "__end__"