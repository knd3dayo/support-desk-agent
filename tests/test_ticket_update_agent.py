from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.agents.production.ticket_update_agent import TicketUpdateAgent
from support_ope_agents.agents.sample.sample_ticket_update_agent import SampleTicketUpdateAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_prepare_ticket_update import build_default_prepare_ticket_update_tool
from support_ope_agents.tools.mcp_client import McpToolInfo
from support_ope_agents.tools.mcp_xml_toolset import XmlMcpToolsetProvider


class _FakeResolver:
    def list_tools(self, server_name: str) -> tuple[McpToolInfo, ...]:
        return (
            McpToolInfo(
                name="get_issue",
                description=f"fetch issue from {server_name}",
                input_schema={"type": "object", "properties": {"issue_number": {"type": "integer"}}},
            ),
            McpToolInfo(
                name="list_issues",
                description=f"list issues from {server_name}",
                input_schema={"type": "object", "properties": {}},
            ),
        )

    def render_tools_xml(self, server_name: str) -> str:
        return f'<tools server="{server_name}"><tool><name>get_issue</name></tool></tools>'

    def list_tool_names(self, _server_name: str) -> set[str]:
        return {"get_issue", "list_issues"}

    def call_tool(self, _server_name: str, tool_name: str, arguments: dict[str, object], *, static_arguments=None) -> str:
        merged = dict(static_arguments or {})
        merged.update(arguments)
        issue_number = merged.get("issue_number")
        if str(issue_number) == "999":
            raise ValueError("issue not found")
        if tool_name == "list_issues":
            return json.dumps(
                {
                    "items": [
                        {"number": "999-1", "title": "Customer cannot login", "state": "open"},
                        {"number": "124", "title": "Customer cannot login from VPN", "state": "open"},
                    ]
                }
            )
        return json.dumps({"title": f"Issue {issue_number}", "body": f"ticket body {issue_number}", "tool": tool_name})


class _FakeChatModel:
    def invoke(self, _messages):
        return AIMessage(
            content="<decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"123\"}</get_arguments><list_tool>skip</list_tool></decision>"
        )


class _FakeNotFoundChatModel:
    def invoke(self, _messages):
        return AIMessage(
            content="<decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"999\"}</get_arguments><list_tool>list_issues</list_tool><list_arguments>{}</list_arguments></decision>"
        )


def _build_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
            "config_paths": {},
            "data_paths": {},
            "interfaces": {},
            "tools": {
                "ticket_sources": {
                    "external": {
                        "enabled": True,
                        "server": "github",
                        "arguments": {"owner": "acme", "repo": "external-support"},
                    }
                }
            },
            "agents": {},
        }
    )


class TicketUpdateAgentTests(unittest.TestCase):
    def test_prepare_update_includes_lookup_summary_in_payload(self) -> None:
        config = _build_config()
        provider = XmlMcpToolsetProvider(backend=_FakeResolver())  # type: ignore[arg-type]
        agent = TicketUpdateAgent(
            config=config,
            prepare_ticket_update_tool=build_default_prepare_ticket_update_tool(config),
            zendesk_reply_tool=lambda *_args, **_kwargs: "",
            redmine_update_tool=lambda *_args, **_kwargs: "",
            ticket_mcp_provider=provider,
        )

        with patch("support_ope_agents.agents.production.ticket_update_agent.build_chat_openai_model", return_value=_FakeChatModel()):
            result = agent.prepare_update(
                {
                    "draft_response": "回答ドラフトです",
                    "external_ticket_id": "123",
                    "intake_ticket_context_summary": {},
                }
            )

        payload = str(result.get("ticket_update_payload") or "")
        self.assertIn("Customer reply prepared:", payload)
        self.assertIn("回答ドラフトです", payload)
        self.assertIn("External ticket id: 123", payload)
        self.assertIn("Issue 123", payload)

    def test_sample_prepare_update_includes_lookup_summary_in_payload(self) -> None:
        config = _build_config()
        provider = XmlMcpToolsetProvider(backend=_FakeResolver())  # type: ignore[arg-type]
        agent = SampleTicketUpdateAgent(
            config=config,
            ticket_mcp_provider=provider,
            prepare_ticket_update_tool=build_default_prepare_ticket_update_tool(config),
        )

        with patch("support_ope_agents.agents.sample.sample_ticket_update_agent.build_chat_openai_model", return_value=_FakeChatModel()):
            result = agent.prepare_update(
                {
                    "draft_response": "回答ドラフトです",
                    "external_ticket_id": "123",
                    "intake_ticket_context_summary": {},
                }
            )

        payload = str(result.get("ticket_update_payload") or "")
        self.assertIn("Customer reply prepared:", payload)
        self.assertIn("External ticket id: 123", payload)
        self.assertIn("Issue 123", payload)

    def test_prepare_update_adds_followup_question_when_ticket_not_found(self) -> None:
        config = _build_config()
        provider = XmlMcpToolsetProvider(backend=_FakeResolver())  # type: ignore[arg-type]
        agent = TicketUpdateAgent(
            config=config,
            prepare_ticket_update_tool=build_default_prepare_ticket_update_tool(config),
            zendesk_reply_tool=lambda *_args, **_kwargs: "",
            redmine_update_tool=lambda *_args, **_kwargs: "",
            ticket_mcp_provider=provider,
        )

        with patch(
            "support_ope_agents.agents.production.ticket_update_agent.build_chat_openai_model",
            return_value=_FakeNotFoundChatModel(),
        ):
            result = agent.prepare_update(
                {
                    "draft_response": "ログインできません",
                    "external_ticket_id": "999",
                    "intake_ticket_context_summary": {},
                }
            )

        payload = str(result.get("ticket_update_payload") or "")
        self.assertIn("External ticket follow-up required:", payload)
        self.assertIn("指定された external ticket id '999' は見つかりませんでした。", payload)
        self.assertIn("999-1 / Customer cannot login / open", payload)


if __name__ == "__main__":
    unittest.main()