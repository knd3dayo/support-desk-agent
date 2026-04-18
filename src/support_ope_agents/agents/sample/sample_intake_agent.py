from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.models.state import CaseState


class SampleIntakeClassification(BaseModel):
    category: str = Field(default="ambiguous_case")
    urgency: str = Field(default="medium")
    investigation_focus: str = Field(default="問い合わせ内容の事実関係を確認する")
    reason: str = Field(default="")


@dataclass(slots=True)
class SampleIntakeAgent(AbstractAgent):
    config: AppConfig

    @staticmethod
    def _default_issue() -> str:
        return "ログインできず、昨日の夕方から 500 エラーが発生しているため確認してください。"

    def _build_classification_prompt(self, raw_issue: str) -> str:
        return (
            "あなたは問い合わせ受付の最小サンプル IntakeAgent です。\n"
            "問い合わせを以下の schema に従って分類してください。\n"
            "- category: specification_inquiry / incident_investigation / ambiguous_case のいずれか\n"
            "- urgency: low / medium / high / critical のいずれか\n"
            "- investigation_focus: 調査で最初に確認すべき観点\n"
            "- reason: 分類理由\n"
            f"問い合わせ本文:\n{raw_issue}"
        )

    def prepare_state(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_issue = str(state.get("raw_issue") or "").strip()
        return StateTransitionHelper.intake_triaged(state, masked_issue=raw_issue)

    def classify_issue(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        if not raw_issue:
            return update

        model = build_chat_openai_model(self.config)
        structured_model = model.with_structured_output(SampleIntakeClassification)
        response = structured_model.invoke(
            [
                HumanMessage(content=self._build_classification_prompt(raw_issue)),
            ]
        )
        if isinstance(response, SampleIntakeClassification):
            classification = response
        elif isinstance(response, dict):
            classification = SampleIntakeClassification.model_validate(response)
        elif hasattr(response, "model_dump"):
            classification = SampleIntakeClassification.model_validate(response.model_dump())
        else:
            raise ValueError("SampleIntakeAgent returned an unsupported structured output payload.")

        update["intake_category"] = classification.category
        update["intake_urgency"] = classification.urgency
        update["intake_investigation_focus"] = classification.investigation_focus
        update["intake_classification_reason"] = classification.reason
        return update

    def finalize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        update["next_action"] = NextActionTexts.START_SUPERVISOR_INVESTIGATION
        return update

    def run_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        update = self.prepare_state(state)
        update = self.classify_issue(update)
        return self.finalize_state(update)

    def create_node(self) -> Any:
        graph = StateGraph(CaseState)
        graph.add_node("intake_prepare", lambda state: cast(CaseState, self.prepare_state(cast(dict[str, Any], state))))
        graph.add_node("intake_classify", lambda state: cast(CaseState, self.classify_issue(cast(dict[str, Any], state))))
        graph.add_node("intake_finalize", lambda state: cast(CaseState, self.finalize_state(cast(dict[str, Any], state))))
        graph.add_edge(START, "intake_prepare")
        graph.add_edge("intake_prepare", "intake_classify")
        graph.add_edge("intake_classify", "intake_finalize")
        graph.add_edge("intake_finalize", END)
        return graph.compile()

    def execute(self, *, raw_issue: str) -> dict[str, Any]:
        node = self.create_node()
        return dict(node.invoke({"raw_issue": raw_issue}))

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            INTAKE_AGENT,
            "Triage and initialize the case",
            kind="phase",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_intake_agent_definition() -> AgentDefinition:
        return SampleIntakeAgent.build_agent_definition()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample intake agent")
    parser.add_argument("issue", nargs="?", default=SampleIntakeAgent._default_issue(), help="Customer issue text")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    args = parser.parse_args()

    config = load_config(args.config)
    agent = SampleIntakeAgent(config=config)
    result = agent.execute(raw_issue=args.issue)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())