from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.agents.roles import OBJECTIVE_EVALUATOR, SUPERVISOR_AGENT
from support_desk_agent.config.models import AppConfig
from support_desk_agent.util.langchain import build_chat_openai_model
from support_desk_agent.util.langchain.chat_model import close_chat_openai_model


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
        evaluation_target: Literal["plan", "result"] = "result",
    ) -> ObjectiveEvaluatorStructuredResult:
        return self._invoke_structured_evaluation(evidence, evaluation_target=evaluation_target)

    @staticmethod
    def _build_target_instruction(evaluation_target: Literal["plan", "result"]) -> str:
        if evaluation_target == "plan":
            return (
                "評価対象は調査計画です。"
                "調査範囲の妥当性、根拠ソースの優先順位、不要な作業の有無、"
                "実行順序の適切性、未解決論点の明確さを中心に評価してください。"
            )
        return (
            "評価対象は調査結果です。"
            "根拠の十分性、説明の明確さ、原因候補の妥当性、次アクションの具体性を中心に評価してください。"
            "特に、回答が日本語で完結しているか、実際に確認したログ断片やファイル名を根拠として明示しているかを重視してください。"
            "working memory や progress への記録不足だけで過剰に減点せず、最終回答そのものの品質を優先して評価してください。"
            "primary evidence が与えられている場合、代替証拠の不足だけで過剰に減点せず、その一次情報の読み取り品質を優先してください。"
        )

    def _invoke_structured_evaluation(
        self,
        evidence: dict[str, Any],
        *,
        evaluation_target: Literal["plan", "result"],
    ) -> ObjectiveEvaluatorStructuredResult:
        model = build_chat_openai_model(self.config)
        messages = [
            SystemMessage(
                content=(
                    f"{self.instruction_text.strip()}\n\n"
                    f"{self._build_target_instruction(evaluation_target)}"
                ).strip()
            ),
            HumanMessage(
                content=(
                    f"以下の証拠パックを用いて {evaluation_target} を評価してください。"
                    "structured output schema に厳密に従い、日本語で返してください。\n"
                    + json.dumps(evidence, ensure_ascii=False)
                )
            ),
        ]
        try:
            structured_model = model.with_structured_output(
                ObjectiveEvaluatorStructuredResult,
                method="function_calling",
            )
            try:
                response = structured_model.invoke(messages)
                return self._coerce_structured_result(response)
            except Exception:
                raw_response = model.invoke(messages)
                return self._coerce_structured_result(self._extract_text(raw_response))
        finally:
            close_chat_openai_model(model)

    @staticmethod
    def _extract_text(response: Any) -> str:
        if isinstance(response, AIMessage):
            return str(response.content)
        if hasattr(response, "content"):
            return str(getattr(response, "content"))
        return str(response)

    @classmethod
    def _coerce_structured_result(cls, response: Any) -> ObjectiveEvaluatorStructuredResult:
        if isinstance(response, ObjectiveEvaluatorStructuredResult):
            return response
        if isinstance(response, str):
            parsed = cls._parse_json_payload(response)
            return ObjectiveEvaluatorStructuredResult.model_validate(cls._unwrap_result_payload(parsed))
        if isinstance(response, dict):
            return ObjectiveEvaluatorStructuredResult.model_validate(cls._unwrap_result_payload(response))
        if hasattr(response, "model_dump"):
            return ObjectiveEvaluatorStructuredResult.model_validate(cls._unwrap_result_payload(response.model_dump()))
        raise ValueError("ObjectiveEvaluator returned an unsupported structured output payload.")

    @staticmethod
    def _parse_json_payload(raw_text: str) -> dict[str, Any]:
        candidate = raw_text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if candidate.startswith("json"):
                candidate = candidate[4:].lstrip()
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("ObjectiveEvaluator raw fallback did not return a JSON object.")
        return parsed

    @classmethod
    def _unwrap_result_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        required_fields = {
            "criterion_evaluations",
            "agent_evaluations",
            "overall_summary",
            "improvement_points",
            "overall_score",
        }
        if required_fields.issubset(payload.keys()):
            return payload
        for key in ("structured_response", "result", "output", "response", "args"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return cls._unwrap_result_payload(nested)
        for value in payload.values():
            if isinstance(value, dict):
                try:
                    return cls._unwrap_result_payload(value)
                except ValueError:
                    continue
        raise ValueError("ObjectiveEvaluator structured payload is missing required fields.")

    @staticmethod
    def build_objective_evaluator_definition() -> AgentDefinition:
        return AgentDefinition(
            OBJECTIVE_EVALUATOR,
            "Evaluate support handling objectively for report generation",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )