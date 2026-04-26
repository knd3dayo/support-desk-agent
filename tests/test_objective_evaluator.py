from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from support_ope_agents.agents.objective_evaluator import ObjectiveEvaluator, ObjectiveEvaluatorStructuredResult
from support_ope_agents.config.models import AppConfig


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

    def test_evaluate_closes_model_clients(self) -> None:
        model = Mock()
        model.root_client = Mock()
        model.root_async_client = Mock()
        model.root_async_client.close = AsyncMock()
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

        with patch("support_ope_agents.agents.objective_evaluator.build_chat_openai_model", return_value=model):
            result = evaluator.evaluate(evidence={"raw_issue": "test"})

        self.assertEqual(result.overall_score, 80)
        model.root_client.close.assert_called_once_with()
        model.root_async_client.close.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()