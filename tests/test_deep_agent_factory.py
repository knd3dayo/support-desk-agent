from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.deep_agent_factory import DeepAgentFactory


class _FakeInstructionLoader:
    def load(self, case_id: str, role: str, constraint_mode: str = "default") -> str:
        return f"system prompt for {case_id}/{role}/{constraint_mode}"


class _FakeToolRegistry:
    def get_tools(self, role: str):
        return [SimpleNamespace(name="tool-a", provider="builtin", target="tool-a", handler=lambda: None)]


class _FakeAgentsConfig:
    KnowledgeRetrieverAgent = SimpleNamespace(document_sources=[])
    ComplianceReviewerAgent = SimpleNamespace(document_sources=[])

    @staticmethod
    def resolve_constraint_mode(role: str) -> str:
        return "default"

    @staticmethod
    def get(role: str):
        return None


class _FakeConfig:
    llm = SimpleNamespace(model="gpt-4.1")
    agents = _FakeAgentsConfig()


class DeepAgentFactoryTests(unittest.TestCase):
    def _build_factory(self) -> DeepAgentFactory:
        return DeepAgentFactory(
            config=_FakeConfig(),
            instruction_loader=_FakeInstructionLoader(),
            tool_registry=_FakeToolRegistry(),
            memory_store=object(),
        )

    def test_build_agent_raises_when_deepagents_import_is_unavailable(self) -> None:
        factory = self._build_factory()
        definition = AgentDefinition("DraftWriterAgent", "Write draft", kind="agent", parent_role="SupervisorAgent")

        with patch("support_ope_agents.agents.deep_agent_factory.create_deep_agent", None):
            with self.assertRaisesRegex(RuntimeError, "deepagents package could not be imported"):
                factory.build_agent("CASE-TEST-001", definition)

    def test_build_agent_raises_when_deepagents_initialization_fails(self) -> None:
        factory = self._build_factory()
        definition = AgentDefinition("DraftWriterAgent", "Write draft", kind="agent", parent_role="SupervisorAgent")

        with patch(
            "support_ope_agents.agents.deep_agent_factory.create_deep_agent",
            side_effect=ConnectionError("LLM connection failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "DeepAgents agent initialization failed"):
                factory.build_agent("CASE-TEST-001", definition)


if __name__ == "__main__":
    unittest.main()