from __future__ import annotations

import json
import unittest

from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.registry import ToolRegistry


class _FakeTool:
    def __init__(self, name: str, handler):
        self.name = name
        self.handler = handler


class ToolRegistryTests(unittest.TestCase):
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

    def test_read_investigate_working_memory_for_case_resolves_async_handler(self) -> None:
        registry = ToolRegistry(self._build_config())

        async def _handler(*, case_id: str, workspace_path: str) -> str:
            del case_id, workspace_path
            return json.dumps({"content": "working"}, ensure_ascii=False)

        registry.get_tools = lambda _role: [_FakeTool("write_working_memory", _handler)]  # type: ignore[method-assign]

        result = registry.read_investigate_working_memory_for_case("CASE-TEST", "/tmp/case")

        self.assertEqual(result, "working")


if __name__ == "__main__":
    unittest.main()