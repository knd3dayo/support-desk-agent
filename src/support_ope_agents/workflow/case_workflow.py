from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

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
    return update


def _intake(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "TRIAGED"
    return update


def _investigation(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "INVESTIGATING"
    return update


def _resolution(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "DRAFT_READY"
    return update


def _wait_for_approval(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "WAITING_APPROVAL"
    update.setdefault("approval_decision", "pending")
    return update


def _ticket_update(state: CaseState) -> CaseState:
    update = dict(state)
    update["status"] = "CLOSED"
    return update


def _route_after_approval(state: CaseState) -> str:
    decision = str(state.get("approval_decision", "pending")).lower()
    if decision == "approved":
        return "ticket_update"
    if decision == "rejected":
        return "resolution"
    if decision == "reinvestigate":
        return "investigation"
    return "__end__"