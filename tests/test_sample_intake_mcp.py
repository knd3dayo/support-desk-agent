from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from support_ope_agents.agents.sample.sample_intake_agent import SampleIntakeAgent
from support_ope_agents.config.models import AppConfig


class _IssueNumberArgs(BaseModel):
    issue_number: int


class _SearchIssuesArgs(BaseModel):
    q: str


class _FakeLangChainTool:
    def __init__(self, name: str, description: str, args_schema: type[BaseModel], handler) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self._handler = handler

    def invoke(self, arguments: dict[str, object]) -> str:
        payload = self.args_schema.model_validate(arguments)
        return self._handler(payload.model_dump())


class _FakeResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.raise_not_found_once = False

    def list_tools(self, server_name: str):
        class _Tool:
            def __init__(self, name: str, description: str, input_schema: dict[str, object]):
                self.name = name
                self.description = description
                self.input_schema = input_schema

        return (
            _Tool("get_issue", "Get a GitHub issue", {"type": "object", "properties": {"issue_number": {"type": "integer"}}}),
            _Tool("search_issues", "Search GitHub issues", {"type": "object", "properties": {"q": {"type": "string"}}}),
            _Tool(
                "get_issue_attachments",
                "Get attachment metadata for a GitHub issue",
                {"type": "object", "properties": {"issue_number": {"type": "integer"}}},
            ),
        )

    def list_tool_names(self, server_name: str) -> set[str]:
        return {tool.name for tool in self.list_tools(server_name)}

    def get_langchain_tools(self, server_name: str):
        return (
            _FakeLangChainTool("get_issue", "Get a GitHub issue", _IssueNumberArgs, lambda arguments: self.call_tool(server_name, "get_issue", arguments)),
            _FakeLangChainTool("search_issues", "Search GitHub issues", _SearchIssuesArgs, lambda arguments: self.call_tool(server_name, "search_issues", arguments)),
            _FakeLangChainTool(
                "get_issue_attachments",
                "Get attachment metadata for a GitHub issue",
                _IssueNumberArgs,
                lambda arguments: self.call_tool(server_name, "get_issue_attachments", arguments),
            ),
        )

    def get_agent_tools(self, server_name: str, *, static_arguments=None, on_tool_call=None):
        wrapped_tools = []
        for tool in self.get_langchain_tools(server_name):
            args_schema = getattr(tool, "args_schema", None)

            def _call_tool(*, _tool=tool, **kwargs):
                filtered_arguments = {key: value for key, value in kwargs.items() if value is not None}
                serialized_result = self.call_tool(
                    server_name,
                    _tool.name,
                    filtered_arguments,
                    static_arguments=static_arguments,
                )
                if on_tool_call is not None:
                    on_tool_call(
                        {
                            "tool_name": _tool.name,
                            "arguments": filtered_arguments,
                            "raw_result": serialized_result,
                        }
                    )
                return serialized_result

            tool_kwargs = {
                "func": _call_tool,
                "name": tool.name,
                "description": tool.description,
            }
            if args_schema is not None:
                tool_kwargs["args_schema"] = args_schema
                tool_kwargs["infer_schema"] = False
            wrapped_tools.append(StructuredTool.from_function(**tool_kwargs))
        return tuple(wrapped_tools)

    def render_tools_xml(self, server_name: str) -> str:
        return f"<tools server=\"{server_name}\"></tools>"

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
        *,
        static_arguments: dict[str, object] | None = None,
    ) -> str:
        merged_arguments = dict(static_arguments or {})
        merged_arguments.update(arguments)
        self.calls.append((server_name, tool_name, merged_arguments))
        if self.raise_not_found_once and tool_name == "get_issue":
            self.raise_not_found_once = False
            raise ValueError("Issue not found: 404")
        if tool_name == "search_issues":
            return '{"items":[{"number":121,"title":"Login failure incident","state":"open"},{"number":123,"title":"Login 500 on production","state":"open"}]}'
        if tool_name == "get_issue_attachments":
            return '{"items":[{"name":"error-screenshot.png","download_url":"https://example.invalid/error-screenshot.png"}]}'
        return '{"title":"Issue 123","state":"open","body":"Customer impact details"}'


class _FakeStructuredModel:
    def invoke(self, _messages):
        return {
            "category": "incident_investigation",
            "urgency": "high",
            "investigation_focus": "障害影響を切り分ける",
            "reason": "mocked classification",
        }


class _FakeChatModel:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def with_structured_output(self, _schema):
        return _FakeStructuredModel()

    def invoke(self, _messages):
        if not self._responses:
            raise AssertionError("unexpected extra invoke")
        return AIMessage(content=self._responses.pop(0))


class _FakeReactAgent:
    def __init__(self, tools, scenario):
        self._tools = {tool.name: tool for tool in tools}
        self._scenario = scenario

    def invoke(self, _input):
        return {"messages": [AIMessage(content=self._scenario(self._tools))]}


class _FakeUrlResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeUrlResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class SampleIntakeMcpTests(unittest.TestCase):
    def _build_config(self) -> AppConfig:
        return AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "tools": {
                    "mcp_manifest_path": "/tmp/test-mcp.json",
                    "logical_tools": {
                        "external_ticket": {
                            "enabled": True,
                            "provider": "mcp",
                            "server": "github",
                            "description": "external github issues",
                            "arguments": {"owner": "acme", "repo": "external-support"},
                        },
                        "internal_ticket": {
                            "enabled": False,
                            "provider": "mcp",
                            "server": "github-internal",
                            "description": "internal github issues",
                            "arguments": {"owner": "acme", "repo": "internal-support"},
                        },
                    }
                },
                "agents": {},
            }
        )

    @staticmethod
    def _react_agent_factory(scenario):
        def _factory(_model, tools, **_kwargs):
            return _FakeReactAgent(tools, scenario)

        return _factory

    def test_hydrates_ticket_context_with_xml_selected_tool(self) -> None:
        config = self._build_config()
        resolver = _FakeResolver()
        agent = SampleIntakeAgent(config=config, ticket_mcp_client=resolver)  # type: ignore[arg-type]

        def _scenario(tools) -> str:
            raw_result = tools["get_issue"].invoke({"issue_number": "123"})
            return (
                "<result>"
                f"<content>{raw_result}</content>"
                "<suggestion></suggestion>"
                "<attachments>"
                "<attachment>https://example.invalid/files/error-screenshot.png</attachment>"
                "</attachments>"
                "</result>"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "support_ope_agents.agents.sample.sample_intake_agent.create_agent",
                side_effect=self._react_agent_factory(_scenario),
            ), patch(
                "support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model",
                return_value=_FakeChatModel([]),
            ), patch(
                "support_ope_agents.agents.sample.sample_intake_agent.urlopen",
                return_value=_FakeUrlResponse(b"png-binary"),
            ):
                result = agent.create_node().invoke(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "123",
                        "internal_ticket_id": "INT-IGNORE",
                        "external_ticket_lookup_enabled": True,
                        "internal_ticket_lookup_enabled": False,
                    }
                )

            summary = result.get("intake_ticket_context_summary") or {}
            artifacts = result.get("intake_ticket_artifacts") or {}
            self.assertIn("external_ticket", summary)
            self.assertIn("Issue 123", str(summary["external_ticket"]))
            self.assertIn("external_ticket_attachments", summary)
            self.assertIn("https://example.invalid/files/error-screenshot.png", str(summary["external_ticket_attachments"]))
            self.assertTrue(artifacts.get("external_ticket"))
            self.assertTrue(artifacts.get("external_ticket_attachments"))
            self.assertEqual(
                resolver.calls,
                [
                    ("github", "get_issue", {"owner": "acme", "repo": "external-support", "issue_number": 123}),
                ],
            )
            artifact_path = Path(artifacts["external_ticket"][0])
            self.assertTrue(artifact_path.exists())
            attachment_path = Path(artifacts["external_ticket_attachments"][0])
            self.assertTrue(attachment_path.exists())
            self.assertEqual(attachment_path.read_bytes(), b"png-binary")

    def test_invalid_xml_tool_selection_disables_lookup_and_records_error(self) -> None:
        config = self._build_config()
        resolver = _FakeResolver()
        agent = SampleIntakeAgent(config=config, ticket_mcp_client=resolver)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "support_ope_agents.agents.sample.sample_intake_agent.create_agent",
                side_effect=self._react_agent_factory(lambda _tools: "<result><content>broken</content>"),
            ), patch(
                "support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model",
                return_value=_FakeChatModel([]),
            ):
                result = agent.create_node().invoke(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "123",
                        "external_ticket_lookup_enabled": True,
                    }
                )

        self.assertFalse(bool(result.get("external_ticket_lookup_enabled")))
        errors = result.get("agent_errors") or []
        self.assertTrue(errors)
        self.assertIn("no element found", str(errors[0].get("message") or ""))

    def test_not_found_ticket_builds_followup_question_with_candidates(self) -> None:
        config = self._build_config()
        resolver = _FakeResolver()
        resolver.raise_not_found_once = True
        agent = SampleIntakeAgent(config=config, ticket_mcp_client=resolver)  # type: ignore[arg-type]

        def _scenario(tools) -> str:
            try:
                tools["get_issue"].invoke({"issue_number": "999"})
            except Exception:
                tools["search_issues"].invoke({"q": "login 500"})
            return (
                "<result><content></content><suggestion>"
                "指定された external ticket '999' は見つかりませんでした。"
                " このチケットですか？ 候補: 121 / Login failure incident / open | 123 / Login 500 on production / open"
                "</suggestion></result>"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "support_ope_agents.agents.sample.sample_intake_agent.create_agent",
                side_effect=self._react_agent_factory(_scenario),
            ), patch(
                "support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model",
                return_value=_FakeChatModel([]),
            ):
                result = agent.create_node().invoke(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "999",
                        "external_ticket_lookup_enabled": True,
                    }
                )

        questions = result.get("intake_followup_questions") or {}
        self.assertIn("external_ticket_confirmation", questions)
        self.assertIn("このチケットですか？", str(questions["external_ticket_confirmation"]))
        self.assertEqual(str(result.get("status") or ""), "WAITING_CUSTOMER_INPUT")
        self.assertEqual(
            resolver.calls,
            [
                ("github", "get_issue", {"owner": "acme", "repo": "external-support", "issue_number": 999}),
                ("github", "search_issues", {"owner": "acme", "repo": "external-support", "q": "login 500"}),
            ],
        )

    def test_not_found_ticket_skips_question_when_candidates_do_not_match(self) -> None:
        config = self._build_config()

        class _LowMatchResolver(_FakeResolver):
            def call_tool(
                self,
                server_name: str,
                tool_name: str,
                arguments: dict[str, object],
                *,
                static_arguments: dict[str, object] | None = None,
            ) -> str:
                merged_arguments = dict(static_arguments or {})
                merged_arguments.update(arguments)
                self.calls.append((server_name, tool_name, merged_arguments))
                if tool_name == "get_issue":
                    raise ValueError("Issue not found: 404")
                if tool_name == "search_issues":
                    return '{"items":[{"number":12,"title":"Billing question","state":"open"},{"number":45,"title":"Password reset request","state":"open"}]}'
                return super().call_tool(server_name, tool_name, arguments, static_arguments=static_arguments)

        resolver = _LowMatchResolver()
        agent = SampleIntakeAgent(config=config, ticket_mcp_client=resolver)  # type: ignore[arg-type]

        def _scenario(tools) -> str:
            try:
                tools["get_issue"].invoke({"issue_number": "999"})
            except Exception:
                tools["search_issues"].invoke({"q": "login 500"})
            return (
                "<result><content></content><suggestion>"
                "ticket が見つからないため、URL または識別子の再確認が必要です。"
                "</suggestion></result>"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "support_ope_agents.agents.sample.sample_intake_agent.create_agent",
                side_effect=self._react_agent_factory(_scenario),
            ), patch(
                "support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model",
                return_value=_FakeChatModel([]),
            ):
                result = agent.create_node().invoke(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "999",
                        "external_ticket_lookup_enabled": True,
                    }
                )

        questions = result.get("intake_followup_questions") or {}
        self.assertIn("external_ticket_confirmation", questions)
        self.assertIn("URL または識別子の再確認", str(questions["external_ticket_confirmation"]))
        self.assertEqual(str(result.get("status") or ""), "WAITING_CUSTOMER_INPUT")


if __name__ == "__main__":
    unittest.main()