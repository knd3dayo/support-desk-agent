from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage, SystemMessage

from support_desk_agent.agents.objective_evaluator import ObjectiveEvaluator, ObjectiveEvaluatorStructuredResult
from support_desk_agent.config.models import AppConfig


class ObjectiveEvaluatorTests(unittest.TestCase):
    def _build_config(self) -> AppConfig:
        return AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

    def test_evaluate_returns_structured_result(self) -> None:
        model = Mock()
        structured_model = Mock()
        structured_model.invoke.return_value = ObjectiveEvaluatorStructuredResult(
            criterion_evaluations=[],
            agent_evaluations=[],
            overall_summary="ok",
            improvement_points=[],
            overall_score=80,
        )
        model.with_structured_output.return_value = structured_model

        evaluator = ObjectiveEvaluator(config=self._build_config(), instruction_text="instruction")

        with patch("support_desk_agent.agents.objective_evaluator.build_chat_openai_model", return_value=model):
            result = evaluator.evaluate(evidence={"raw_issue": "test"})

        self.assertEqual(result.overall_score, 80)
        model.with_structured_output.assert_called_once_with(
            ObjectiveEvaluatorStructuredResult,
            method="function_calling",
        )

    def test_evaluate_includes_plan_target_specific_instruction(self) -> None:
        model = Mock()
        structured_model = Mock()
        structured_model.invoke.return_value = ObjectiveEvaluatorStructuredResult(
            criterion_evaluations=[],
            agent_evaluations=[],
            overall_summary="ok",
            improvement_points=[],
            overall_score=80,
        )
        model.with_structured_output.return_value = structured_model

        evaluator = ObjectiveEvaluator(config=self._build_config(), instruction_text="instruction")

        with patch("support_desk_agent.agents.objective_evaluator.build_chat_openai_model", return_value=model):
            evaluator.evaluate(evidence={"plan_summary": "test"}, evaluation_target="plan")

        messages = structured_model.invoke.call_args.args[0]
        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIn("評価対象は調査計画", messages[0].content)
        self.assertIsInstance(messages[1], HumanMessage)
        self.assertIn("plan を評価", messages[1].content)

    def test_evaluate_includes_result_quality_priority_instruction(self) -> None:
        model = Mock()
        structured_model = Mock()
        structured_model.invoke.return_value = ObjectiveEvaluatorStructuredResult(
            criterion_evaluations=[],
            agent_evaluations=[],
            overall_summary="ok",
            improvement_points=[],
            overall_score=80,
        )
        model.with_structured_output.return_value = structured_model

        evaluator = ObjectiveEvaluator(config=self._build_config(), instruction_text="instruction")

        with patch("support_desk_agent.agents.objective_evaluator.build_chat_openai_model", return_value=model):
            evaluator.evaluate(evidence={"investigation_summary": "test"}, evaluation_target="result")

        messages = structured_model.invoke.call_args.args[0]
        self.assertIn("日本語で完結", messages[0].content)
        self.assertIn("working memory や progress への記録不足だけで過剰に減点せず", messages[0].content)


if __name__ == "__main__":
    unittest.main()