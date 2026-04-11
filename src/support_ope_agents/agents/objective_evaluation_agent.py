from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import OBJECTIVE_EVALUATION_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import AppConfig


class StructuredCriterionEvaluation(BaseModel):
    title: str
    viewpoint: str
    result: str
    score: int = Field(ge=0, le=100)
    related_checklist_items: list[str] = Field(default_factory=list)


class StructuredAgentEvaluation(BaseModel):
    agent_name: str
    score: int = Field(ge=0, le=100)
    comment: str


class ObjectiveEvaluationStructuredResult(BaseModel):
    criterion_evaluations: list[StructuredCriterionEvaluation]
    agent_evaluations: list[StructuredAgentEvaluation]
    overall_summary: str
    improvement_points: list[str]
    overall_score: int = Field(ge=0, le=100)


def _get_chat_model(config: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.llm.model,
        api_key=SecretStr(config.llm.api_key),
        base_url=config.llm.base_url,
        temperature=0,
    )


@dataclass(frozen=True, slots=True)
class ObjectiveEvaluationAgent:
    config: AppConfig
    instruction_text: str

    name = OBJECTIVE_EVALUATION_AGENT

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
    ) -> ObjectiveEvaluationStructuredResult:
        return self._invoke_structured_evaluation(evidence)

    def _invoke_structured_evaluation(self, evidence: dict[str, Any]) -> ObjectiveEvaluationStructuredResult:
        model = _get_chat_model(self.config)
        structured_model = model.with_structured_output(ObjectiveEvaluationStructuredResult)
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
        if isinstance(response, ObjectiveEvaluationStructuredResult):
            return response
        if isinstance(response, dict):
            return ObjectiveEvaluationStructuredResult.model_validate(response)
        if hasattr(response, "model_dump"):
            return ObjectiveEvaluationStructuredResult.model_validate(response.model_dump())
        raise ValueError("ObjectiveEvaluationAgent returned an unsupported structured output payload.")


def build_objective_evaluation_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        OBJECTIVE_EVALUATION_AGENT,
        "Evaluate support handling objectively for report generation",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )