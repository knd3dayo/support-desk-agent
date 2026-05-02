from __future__ import annotations

import json
import tempfile
import unittest

from support_desk_agent.agents.roles import SUPERVISOR_AGENT
from support_desk_agent.config.models import AppConfig
from support_desk_agent.tools.registry import ToolRegistry


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

    def test_invoke_tool_resolves_async_handler(self) -> None:
        registry = ToolRegistry(self._build_config())

        async def _handler(*, value: str) -> str:
            return f"handled:{value}"

        registry.get_tools = lambda _role: [_FakeTool("write_shared_memory", _handler)]  # type: ignore[method-assign]

        result = registry.invoke_tool("write_shared_memory", "SupervisorAgent", value="ok")

        self.assertEqual(result, "handled:ok")

    def test_supervisor_working_memory_tool_targets_supervisor_memory(self) -> None:
        registry = ToolRegistry(self._build_config())
        handler = registry.get_tool_handler("write_working_memory", SUPERVISOR_AGENT)

        self.assertIsNotNone(handler)

        with tempfile.TemporaryDirectory() as tmpdir:
            raw = registry.invoke_tool("write_working_memory", SUPERVISOR_AGENT, case_id="CASE-TEST", workspace_path=tmpdir)

        payload = json.loads(raw)
        self.assertEqual(payload["agent_name"], SUPERVISOR_AGENT)


if __name__ == "__main__":
    unittest.main()