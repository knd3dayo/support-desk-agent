from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import APPROVAL_AGENT, SUPERVISOR_AGENT
from support_ope_agents.models.state_transitions import StateTransitionHelper
from support_ope_agents.util.formatting import format_result


class SampleApprovalState(TypedDict, total=False):
    status: str
    current_agent: str
    approval_decision: str
    execution_mode: str
    escalation_required: bool
    next_action: str



class SampleApprovalAgent(AbstractAgent):
    def __init__(self, config: Any):
        from support_ope_agents.tools.registry import ToolRegistry
        self.config = config
        self.tool_registry = ToolRegistry(config)

    def wait_for_approval(self, state: dict[str, Any]) -> dict[str, Any]:
        return StateTransitionHelper.waiting_for_approval(state)

    def create_node(self) -> Any:
        graph = StateGraph(SampleApprovalState)
        graph.add_node(
            "wait_for_approval",
            lambda state: cast(SampleApprovalState, self.wait_for_approval(cast(dict[str, Any], state))),
        )
        graph.add_edge(START, "wait_for_approval")
        graph.add_edge("wait_for_approval", END)
        return graph.compile()

    def execute(
        self,
        *,
        execution_mode: str = "action",
        escalation_required: bool = False,
    ) -> dict[str, Any]:
        node = self.create_node()
        return dict(
            node.invoke(
                {
                    "execution_mode": execution_mode,
                    "escalation_required": escalation_required,
                }
            )
        )

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            APPROVAL_AGENT,
            "Request approval before sending updates or escalation drafts",
            kind="phase",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_approval_agent_definition() -> AgentDefinition:
        return SampleApprovalAgent.build_agent_definition()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample approval agent")
    parser.add_argument(
        "--execution-mode",
        choices=("plan", "action"),
        default="action",
        help="Approval scenario to simulate",
    )
    parser.add_argument(
        "--escalation-required",
        action="store_true",
        help="Simulate an escalation approval instead of a normal draft approval",
    )
    args = parser.parse_args()

    agent = SampleApprovalAgent()
    result = agent.execute(
        execution_mode=args.execution_mode,
        escalation_required=args.escalation_required,
    )
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())