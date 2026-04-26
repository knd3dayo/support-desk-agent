from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from support_ope_agents.agents.sample.sample_back_support_escalation_agent import SampleBackSupportEscalationAgent
from support_ope_agents.config.models import AppConfig


class SampleBackSupportEscalationAgentTests(unittest.TestCase):
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

    def test_create_sub_agent_wraps_async_tools_synchronously(self) -> None:
        async def _async_tool(*_args: object, **_kwargs: object) -> str:
            return "ok"

        fake_tool = type("FakeTool", (), {"name": "write_shared_memory", "handler": _async_tool})()

        with tempfile.TemporaryDirectory() as tmpdir:
            agent = SampleBackSupportEscalationAgent(config=self._build_config(), memory_dir=tmpdir)
            with patch.object(agent.tool_registry, "get_tools", return_value=[fake_tool]):
                with patch(
                    "support_ope_agents.agents.sample.sample_back_support_escalation_agent.create_deep_agent_compatible_agent"
                ) as create_mock:
                    create_mock.return_value = object()
                    agent.create_sub_agent(query="エスカレーション文を作成")

        wrapped_tool = create_mock.call_args.kwargs["tools"][0]
        self.assertEqual(wrapped_tool(), "ok")