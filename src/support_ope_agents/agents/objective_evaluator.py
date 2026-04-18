from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import OBJECTIVE_EVALUATOR, SUPERVISOR_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.langchain import build_chat_openai_model


class StructuredCriterionEvaluation(BaseModel):
    criterion_key: str | None = None
    title: str
    viewpoint: str
    result: str
    score: int = Field(ge=0, le=100)
    related_checklist_items: list[str] = Field(default_factory=list)


class StructuredAgentEvaluation(BaseModel):
    agent_name: str
    score: int = Field(ge=0, le=100)
    comment: str


class ObjectiveEvaluatorStructuredResult(BaseModel):
    criterion_evaluations: list[StructuredCriterionEvaluation]
    agent_evaluations: list[StructuredAgentEvaluation]
    overall_summary: str
    improvement_points: list[str]
    overall_score: int = Field(ge=0, le=100)
@dataclass(frozen=True, slots=True)
class ObjectiveEvaluator:
    config: AppConfig
    instruction_text: str

    name = OBJECTIVE_EVALUATOR

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
    ) -> ObjectiveEvaluatorStructuredResult:
        return self._invoke_structured_evaluation(evidence)

    def _invoke_structured_evaluation(self, evidence: dict[str, Any]) -> ObjectiveEvaluatorStructuredResult:
        model = build_chat_openai_model(self.config)
        structured_model = model.with_structured_output(ObjectiveEvaluatorStructuredResult)
        response = structured_model.invoke([
            SystemMessage(content=self.instruction_text.strip()),
            HumanMessage(
                content=(
                    "以下の証拠パックを用いてサポート対応を評価してください。"
                    "structured output schema に厳密に従い、日本語で返してください。\n"
                    + json.dumps(evidence, ensure_ascii=False)
                )
            ),
        ])
        if isinstance(response, ObjectiveEvaluatorStructuredResult):
            return response
        if isinstance(response, dict):
            return ObjectiveEvaluatorStructuredResult.model_validate(response)
        if hasattr(response, "model_dump"):
            return ObjectiveEvaluatorStructuredResult.model_validate(response.model_dump())
        raise ValueError("ObjectiveEvaluator returned an unsupported structured output payload.")

    @staticmethod
    def build_objective_evaluator_definition() -> AgentDefinition:
        return AgentDefinition(
            OBJECTIVE_EVALUATOR,
            "Evaluate support handling objectively for report generation",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )