from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support_ope_agents.util.langchain.agent_factory import create_deep_agent_compatible_agent


class _FakeCompiledAgent:
    def __init__(self) -> None:
        self.config = None

    def with_config(self, config: dict[str, object]) -> "_FakeCompiledAgent":
        self.config = config
        return self


class AgentFactoryTests(unittest.TestCase):
    def test_create_deep_agent_compatible_agent_passes_context_schema(self) -> None:
        fake_agent = _FakeCompiledAgent()
        context_schema = type("ContextSchema", (), {})

        with patch("support_ope_agents.util.langchain.agent_factory.create_agent", return_value=fake_agent) as create_agent_mock:
            create_deep_agent_compatible_agent(
                model=SimpleNamespace(),
                tools=[],
                context_schema=context_schema,
                include_filesystem=False,
                include_patch_tool_calls=False,
                include_todo_list=False,
            )

        self.assertIs(create_agent_mock.call_args.kwargs["context_schema"], context_schema)

    def test_create_deep_agent_compatible_agent_adds_memory_and_skills_middleware(self) -> None:
        fake_agent = _FakeCompiledAgent()
        fake_model = SimpleNamespace()

        with patch("support_ope_agents.util.langchain.agent_factory.create_agent", return_value=fake_agent) as create_agent_mock:
            with patch("support_ope_agents.util.langchain.agent_factory.StateBackend", return_value="state-backend"):
                with patch("support_ope_agents.util.langchain.agent_factory.FilesystemMiddleware", side_effect=lambda **kwargs: ("fs", kwargs)):
                    with patch("support_ope_agents.util.langchain.agent_factory.PatchToolCallsMiddleware", return_value=("patch", {})):
                        with patch("support_ope_agents.util.langchain.agent_factory.MemoryMiddleware", side_effect=lambda **kwargs: ("memory", kwargs)):
                            with patch("support_ope_agents.util.langchain.agent_factory.SkillsMiddleware", side_effect=lambda **kwargs: ("skills", kwargs)):
                                create_deep_agent_compatible_agent(
                                    model=fake_model,
                                    tools=[],
                                    memory=["/AGENTS.md"],
                                    skills=["/skills/"],
                                )

        middleware = create_agent_mock.call_args.kwargs["middleware"]
        self.assertEqual(middleware[1][0], "skills")
        self.assertEqual(middleware[1][1]["sources"], ["/skills/"])
        self.assertEqual(middleware[-1][0], "memory")
        self.assertEqual(middleware[-1][1]["sources"], ["/AGENTS.md"])

    def test_create_deep_agent_compatible_agent_uses_custom_summarization_factory(self) -> None:
        fake_agent = _FakeCompiledAgent()

        class _FakeModel:
            pass

        fake_model = _FakeModel()

        with patch("support_ope_agents.util.langchain.agent_factory.create_agent", return_value=fake_agent) as create_agent_mock:
            with patch("support_ope_agents.util.langchain.agent_factory.BaseChatModel", _FakeModel):
                with patch("support_ope_agents.util.langchain.agent_factory.StateBackend", return_value="state-backend"):
                    with patch("support_ope_agents.util.langchain.agent_factory.FilesystemMiddleware", side_effect=lambda **kwargs: ("fs", kwargs)):
                        with patch("support_ope_agents.util.langchain.agent_factory.PatchToolCallsMiddleware", return_value=("patch", {})):
                            create_deep_agent_compatible_agent(
                                model=fake_model,
                                tools=[],
                                include_summarization=True,
                                summarization_middleware_factory=lambda model, backend: ("summarization", {"model": model, "backend": backend}),
                            )

        middleware = create_agent_mock.call_args.kwargs["middleware"]
        self.assertEqual(middleware[2][0], "summarization")
        self.assertIs(middleware[2][1]["model"], fake_model)