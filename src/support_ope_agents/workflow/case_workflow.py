from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    INTAKE_AGENT,
    RESOLUTION_AGENT,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
)
from support_ope_agents.workflow.state import CaseState


def build_case_workflow(*, checkpointer: Any | None = None):
    graph = StateGraph(CaseState)
    graph.add_node("receive_case", _receive_case)
    graph.add_node("intake", _intake)
    graph.add_node("investigation", _investigation)
    graph.add_node("resolution", _resolution)
    graph.add_node("wait_for_approval", _wait_for_approval)
    graph.add_node("ticket_update", _ticket_update)

    graph.add_edge(START, "receive_case")
    graph.add_edge("receive_case", "intake")
    graph.add_edge("intake", "investigation")
    graph.add_edge("investigation", "resolution")
    graph.add_edge("resolution", "wait_for_approval")
    graph.add_conditional_edges(
        "wait_for_approval",
        _route_after_approval,
        {
            "ticket_update": "ticket_update",
            "resolution": "resolution",
            "investigation": "investigation",
            "__end__": END,
        },
    )
    graph.add_edge("ticket_update", END)
    return graph.compile(checkpointer=checkpointer) if checkpointer is not None else graph.compile()


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


def _intake(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "TRIAGED"
    update["current_agent"] = INTAKE_AGENT
    if update.get("execution_mode") == "plan":
        update["next_action"] = "ユーザーに計画を提示して承認を得る"
    return cast(CaseState, update)


def _investigation(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "INVESTIGATING"
    update["current_agent"] = SUPERVISOR_AGENT
    if update.get("execution_mode") == "action":
        update["investigation_summary"] = str(update.get("investigation_summary") or "SuperVisorAgent 配下でログ解析とナレッジ探索を開始する準備が整っています。")
    return cast(CaseState, update)


def _resolution(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "DRAFT_READY"
    update["current_agent"] = RESOLUTION_AGENT
    if update.get("execution_mode") == "plan":
        update["draft_response"] = "plan モードでは実行計画のみを返却し、action モードでドラフト生成へ進みます。"
    else:
        update.setdefault("draft_response", "action モードで回答ドラフトを生成する準備が整っています。")
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


def _ticket_update(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "CLOSED"
    update["current_agent"] = TICKET_UPDATE_AGENT
    update["next_action"] = "Zendesk と Redmine の更新を実行する"
    return cast(CaseState, update)


def _route_after_approval(state: CaseState) -> str:
    decision = str(state.get("approval_decision", "pending")).lower()
    if decision in {"approved", "approve"}:
        return "ticket_update"
    if decision in {"rejected", "reject"}:
        return "resolution"
    if decision == "reinvestigate":
        return "investigation"
    return "__end__"