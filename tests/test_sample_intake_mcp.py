from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.agents.sample.sample_intake_agent import SampleIntakeAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.mcp_xml_toolset import XmlMcpToolsetProvider


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

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, object]) -> str:
        self.calls.append((server_name, tool_name, arguments))
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


class SampleIntakeMcpTests(unittest.TestCase):
    def _build_config(self) -> AppConfig:
        return AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "tools": {
                    "ticket_sources": {
                        "external": {
                            "enabled": True,
                            "server": "github",
                            "description": "external github issues",
                            "arguments": {"owner": "acme", "repo": "external-support"},
                        },
                        "internal": {
                            "enabled": False,
                            "server": "github-internal",
                            "description": "internal github issues",
                            "arguments": {"owner": "acme", "repo": "internal-support"},
                        },
                    }
                },
                "agents": {},
            }
        )

    def test_hydrates_ticket_context_with_xml_selected_tool(self) -> None:
        config = self._build_config()
        resolver = _FakeResolver()
        provider = XmlMcpToolsetProvider(backend=resolver)  # type: ignore[arg-type]
        agent = SampleIntakeAgent(config=config, ticket_mcp_provider=provider)
        model = _FakeChatModel(
            [
                "<decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"123\"}</get_arguments><list_tool>search_issues</list_tool><list_arguments>{\"q\": \"login 500\"}</list_arguments><get_attachment_tool>get_issue_attachments</get_attachment_tool><get_attachment_arguments>{\"issue_number\": \"123\"}</get_attachment_arguments><reason>direct issue lookup with attachments</reason></decision>"
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model", return_value=model):
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
            self.assertEqual("Attachment metadata retrieved.", str(summary["external_ticket_attachments"]))
            self.assertTrue(artifacts.get("external_ticket"))
            self.assertTrue(artifacts.get("external_ticket_attachments"))
            self.assertEqual(
                resolver.calls,
                [
                    ("github", "get_issue", {"owner": "acme", "repo": "external-support", "issue_number": 123}),
                    (
                        "github",
                        "get_issue_attachments",
                        {"owner": "acme", "repo": "external-support", "issue_number": 123},
                    ),
                ],
            )
            artifact_path = Path(artifacts["external_ticket"][0])
            self.assertTrue(artifact_path.exists())

    def test_invalid_xml_tool_selection_disables_lookup_and_records_error(self) -> None:
        config = self._build_config()
        resolver = _FakeResolver()
        provider = XmlMcpToolsetProvider(backend=resolver)  # type: ignore[arg-type]
        agent = SampleIntakeAgent(config=config, ticket_mcp_provider=provider)
        model = _FakeChatModel(
            [
                "<decision><get_tool>unknown_tool</get_tool><get_arguments>{}</get_arguments><list_tool>skip</list_tool><get_attachment_tool>skip</get_attachment_tool></decision>"
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model", return_value=model):
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
        self.assertIn("selected MCP tool does not exist", str(errors[0].get("message") or ""))

    def test_not_found_ticket_builds_followup_question_with_candidates(self) -> None:
        config = self._build_config()
        resolver = _FakeResolver()
        resolver.raise_not_found_once = True
        provider = XmlMcpToolsetProvider(backend=resolver)  # type: ignore[arg-type]
        agent = SampleIntakeAgent(config=config, ticket_mcp_provider=provider)
        model = _FakeChatModel(
            [
                "<decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"999\"}</get_arguments><list_tool>search_issues</list_tool><list_arguments>{\"q\": \"login 500\"}</list_arguments><get_attachment_tool>skip</get_attachment_tool><reason>try exact lookup then search nearby candidates</reason></decision>",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model", return_value=model):
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
            def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, object]) -> str:
                self.calls.append((server_name, tool_name, arguments))
                if tool_name == "get_issue":
                    raise ValueError("Issue not found: 404")
                if tool_name == "search_issues":
                    return '{"items":[{"number":12,"title":"Billing question","state":"open"},{"number":45,"title":"Password reset request","state":"open"}]}'
                return super().call_tool(server_name, tool_name, arguments)

        resolver = _LowMatchResolver()
        provider = XmlMcpToolsetProvider(backend=resolver)  # type: ignore[arg-type]
        agent = SampleIntakeAgent(config=config, ticket_mcp_provider=provider)
        model = _FakeChatModel(
            [
                "<decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"999\"}</get_arguments><list_tool>search_issues</list_tool><list_arguments>{\"q\": \"login 500\"}</list_arguments><get_attachment_tool>skip</get_attachment_tool><reason>try exact lookup then search nearby candidates</reason></decision>",
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model", return_value=model):
                result = agent.create_node().invoke(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "999",
                        "external_ticket_lookup_enabled": True,
                    }
                )

        questions = result.get("intake_followup_questions") or {}
        self.assertFalse(bool(questions))
        errors = result.get("agent_errors") or []
        self.assertTrue(errors)
        self.assertIn("Issue not found: 404", str(errors[0].get("message") or ""))


if __name__ == "__main__":
    unittest.main()