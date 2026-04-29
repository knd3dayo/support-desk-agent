from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from support_desk_agent.agents.roles import SUPERVISOR_AGENT
from support_desk_agent.agents.sample.sample_intake_agent import SampleIntakeAgent
from support_desk_agent.agents.sample.sample_supervisor_agent import SampleSupervisorAgent
from support_desk_agent.models.state import CaseState
from support_desk_agent.models.state_transitions import CaseStatuses

class CaseWorkflow:

    def build_case_workflow(
            self,
            *,
            checkpointer: Any | None = None,
            intake_executor: SampleIntakeAgent,
            supervisor_executor: SampleSupervisorAgent,
    ):
        graph = StateGraph(CaseState)
        graph.add_node("receive_case", self._receive_case)
        graph.add_node("intake_subgraph", intake_executor.create_node())
        graph.add_node("supervisor_subgraph", supervisor_executor.create_node())

        graph.add_edge(START, "receive_case")
        graph.add_edge("receive_case", "intake_subgraph")
        graph.add_conditional_edges(
            "intake_subgraph",
            self._route_after_intake,
            {
                "supervisor_subgraph": "supervisor_subgraph",
                "__end__": END,
            },
        )
        graph.add_edge("supervisor_subgraph", END)
        return graph.compile(checkpointer=checkpointer) if checkpointer is not None else graph.compile()


    def reconstruct_main_workflow_path(self, state: CaseState) -> tuple[str, ...]:
        path: list[str] = [
            "receive_case",
            "intake_prepare",
            "intake_classify",
            "intake_mcp_tickets",
            "intake_ticket_followup_decision",
        ]

        if str(state.get("status") or "") == CaseStatuses.WAITING_CUSTOMER_INPUT:
            path.append("intake_request_customer_input")
            return tuple(path)

        path.append("intake_finalize")
        path.append("investigation")
        after_investigation = self._route_after_investigation(state)
        if after_investigation == "escalation_review":
            path.extend(["escalation_review", "wait_for_approval"])
        else:
            path.extend(["draft_review", "wait_for_approval"])

        after_approval = self._route_after_approval(state)
        if after_approval == "ticket_update_subgraph":
            path.extend(["ticket_update_prepare", "ticket_update_execute"])
        elif after_approval == "draft_review":
            path.extend(["draft_review", "wait_for_approval"])
        elif after_approval == "investigation":
            path.append("investigation")

        return tuple(path)

    def _receive_case(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = CaseStatuses.RECEIVED
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
            return "ticket_update_subgraph"
        if decision in {"rejected", "reject"}:
            return "draft_review"
        if decision == "reinvestigate":
            return "investigation"
        return "__end__"


    def _route_after_intake(self, state: CaseState) -> str:
        if str(state.get("status") or "") == CaseStatuses.WAITING_CUSTOMER_INPUT:
            return "__end__"
        return "supervisor_subgraph"


    def _route_after_investigation(self, state: CaseState) -> str:
        return SampleSupervisorAgent.route_after_investigation(cast(dict[str, object], state))