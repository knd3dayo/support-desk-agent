from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.intake_agent import IntakePhaseExecutor
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    INTAKE_AGENT,
    BACK_SUPPORT_INQUIRY_WRITER_AGENT,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
)
from support_ope_agents.workflow.state import CaseState


def build_case_workflow(
    *,
    checkpointer: Any | None = None,
    intake_executor: IntakePhaseExecutor | None = None,
    supervisor_executor: SupervisorPhaseExecutor | None = None,
):
    graph = StateGraph(CaseState)
    graph.add_node("receive_case", _receive_case)
    graph.add_node("intake", _build_intake_node(intake_executor))
    graph.add_node("investigation", _build_investigation_node(supervisor_executor))
    graph.add_node("draft_review", _build_draft_review_node(supervisor_executor))
    graph.add_node("escalation_review", _build_escalation_review_node(supervisor_executor))
    graph.add_node("wait_for_customer_input", _wait_for_customer_input)
    graph.add_node("wait_for_approval", _wait_for_approval)
    _add_ticket_update_subgraph(graph)

    graph.add_edge(START, "receive_case")
    graph.add_edge("receive_case", "intake")
    graph.add_conditional_edges(
        "intake",
        _route_after_intake,
        {
            "investigation": "investigation",
            "wait_for_customer_input": "wait_for_customer_input",
        },
    )
    graph.add_conditional_edges(
        "investigation",
        _route_after_investigation,
        {
            "draft_review": "draft_review",
            "escalation_review": "escalation_review",
            "intake": "intake",
        },
    )
    graph.add_edge("escalation_review", "wait_for_approval")
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
        update.setdefault("intake_rework_required", False)
        update.setdefault("intake_missing_fields", [])
        update.setdefault("intake_followup_questions", {})
        update.setdefault("customer_followup_answers", {})
        if update.get("execution_mode") == "plan":
            update["next_action"] = "ユーザーに計画を提示して承認を得る"
        else:
            update["next_action"] = "SuperVisorAgent が調査フェーズを開始する"
        return cast(CaseState, update)


def _build_investigation_node(supervisor_executor: SupervisorPhaseExecutor | None):
    executor = supervisor_executor or _NoOpSupervisorExecutor()

    def _investigation(state: CaseState) -> CaseState:
        return cast(CaseState, executor.execute_investigation(state))

    return _investigation


def _build_draft_review_node(supervisor_executor: SupervisorPhaseExecutor | None):
    executor = supervisor_executor or _NoOpSupervisorExecutor()

    def _draft_review(state: CaseState) -> CaseState:
        return cast(CaseState, executor.execute_draft_review(state))

    return _draft_review


def _build_escalation_review_node(supervisor_executor: SupervisorPhaseExecutor | None):
    executor = supervisor_executor or _NoOpSupervisorExecutor()

    def _escalation_review(state: CaseState) -> CaseState:
        return cast(CaseState, executor.execute_escalation_review(state))

    return _escalation_review


class _NoOpSupervisorExecutor:
    def execute_investigation(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "INVESTIGATING"
        update["current_agent"] = SUPERVISOR_AGENT
        update.setdefault("intake_rework_required", False)
        if update.get("execution_mode") == "action":
            update["investigation_summary"] = str(update.get("investigation_summary") or "SuperVisorAgent 配下でログ解析とナレッジ探索を開始する準備が整っています。")
        return cast(CaseState, update)

    def execute_draft_review(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "DRAFT_READY"
        update["current_agent"] = SUPERVISOR_AGENT
        if update.get("execution_mode") == "plan":
            update["draft_response"] = "plan モードでは SuperVisorAgent がドラフト作成とレビュー方針のみを返却し、action モードで実際の生成へ進みます。"
        else:
            update.setdefault("draft_response", "action モードで SuperVisorAgent 配下のドラフト作成とレビューを開始する準備が整っています。")
        return cast(CaseState, update)

    def execute_escalation_review(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "DRAFT_READY"
        update["current_agent"] = BACK_SUPPORT_INQUIRY_WRITER_AGENT
        update.setdefault("escalation_required", True)
        update.setdefault("escalation_reason", "調査結果だけでは確実な回答が困難")
        update.setdefault("escalation_summary", "バックサポート向けエスカレーション要約を準備しました。")
        update.setdefault(
            "escalation_draft",
            "追加ログと再現条件を確認するため、バックサポート向け問い合わせ文案を準備します。",
        )
        update["draft_response"] = str(update.get("escalation_draft") or "")
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
    elif update.get("escalation_required"):
        update["next_action"] = "エスカレーション問い合わせ文案を確認し、送付可否を承認してください。"
    else:
        update["next_action"] = "回答ドラフトを確認し、チケット更新を承認してください。"
    return cast(CaseState, update)


def _wait_for_customer_input(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "WAITING_CUSTOMER_INPUT"
    update["current_agent"] = INTAKE_AGENT
    if not update.get("next_action"):
        update["next_action"] = "IntakeAgent の質問に回答し、追加情報を提供してください。"
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


def _route_after_intake(state: CaseState) -> str:
    if state.get("status") == "WAITING_CUSTOMER_INPUT":
        return "wait_for_customer_input"
    return "investigation"


def _route_after_investigation(state: CaseState) -> str:
    if state.get("intake_rework_required"):
        return "intake"
    if state.get("escalation_required"):
        return "escalation_review"
    return "draft_review"