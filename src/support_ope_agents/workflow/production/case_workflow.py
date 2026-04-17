from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.production.approval_agent import ApprovalAgent
from support_ope_agents.agents.production.intake_agent import IntakeAgent
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.agents.production.ticket_update_agent import TicketUpdateAgent
from support_ope_agents.agents.roles import (
    BACK_SUPPORT_INQUIRY_WRITER_AGENT,
    SUPERVISOR_AGENT,
)
from support_ope_agents.workflow.state import CaseState

class CaseWorkflow:

    def build_case_workflow(
            self,
            *,
            checkpointer: Any | None = None,
            intake_executor: IntakeAgent,
            approval_executor: ApprovalAgent,
            ticket_update_executor: TicketUpdateAgent,
            supervisor_executor: SupervisorPhaseExecutor,
    ):
        graph = StateGraph(CaseState)
        graph.add_node("receive_case", self._receive_case)
        graph.add_node("intake_subgraph", intake_executor.create_node())
        graph.add_node("supervisor_subgraph", supervisor_executor.create_node())
        graph.add_node("wait_for_customer_input", intake_executor.create_wait_node())
        graph.add_node("wait_for_approval", approval_executor.create_node())
        graph.add_node("ticket_update_subgraph", ticket_update_executor.create_node())

        graph.add_edge(START, "receive_case")
        graph.add_edge("receive_case", "intake_subgraph")
        graph.add_conditional_edges(
            "intake_subgraph",
            self._route_after_intake,
            {
                "investigation": "supervisor_subgraph",
                "wait_for_customer_input": "wait_for_customer_input",
            },
        )
        graph.add_edge("supervisor_subgraph", "wait_for_approval")
        graph.add_conditional_edges(
            "wait_for_approval",
            self._route_after_approval,
            {
                "ticket_update_prepare": "ticket_update_subgraph",
                "draft_review": "supervisor_subgraph",
                "investigation": "supervisor_subgraph",
                "__end__": END,
            },
        )
        graph.add_edge("ticket_update_subgraph", END)
        return graph.compile(checkpointer=checkpointer) if checkpointer is not None else graph.compile()


    def reconstruct_main_workflow_path(self, state: CaseState) -> tuple[str, ...]:
        path: list[str] = [
            "receive_case",
            "intake_prepare",
            "intake_mask",
            "intake_hydrate_tickets",
            "intake_classify",
            "intake_finalize",
        ]

        after_intake = self._route_after_intake(state)
        if after_intake == "wait_for_customer_input":
            path.append("wait_for_customer_input")
            return tuple(path)

        path.append("investigation")
        after_investigation = self._route_after_investigation(state)
        if after_investigation == "escalation_review":
            path.extend(["escalation_review", "wait_for_approval"])
        else:
            review_iterations = max(1, int(state.get("draft_review_iterations") or 1))
            for _ in range(review_iterations):
                path.extend(["draft_review", "wait_for_approval"])

        after_approval = self._route_after_approval(state)
        if after_approval == "ticket_update_prepare":
            path.extend(["ticket_update_prepare", "ticket_update_execute"])
        elif after_approval == "draft_review":
            path.extend(["draft_review", "wait_for_approval"])
        elif after_approval == "investigation":
            path.append("investigation")

        return tuple(path)

    def _receive_case(self, state: CaseState) -> CaseState:
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


    def _route_after_approval(self, state: CaseState) -> str:
        decision = str(state.get("approval_decision", "pending")).lower()
        if decision in {"approved", "approve"}:
            return "ticket_update_prepare"
        if decision in {"rejected", "reject"}:
            return "draft_review"
        if decision == "reinvestigate":
            return "investigation"
        return "__end__"


    def _route_after_intake(self, state: CaseState) -> str:
        if state.get("status") == "WAITING_CUSTOMER_INPUT":
            return "wait_for_customer_input"
        return "investigation"


    def _route_after_investigation(self, state: CaseState) -> str:
        return SupervisorPhaseExecutor.route_after_investigation(cast(dict[str, object], state))