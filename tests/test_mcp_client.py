from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.config import McpManifest
from support_ope_agents.config import McpServerConfig
from support_ope_agents.config.models import AppConfig
from support_ope_agents.config.models import McpToolBinding
from support_ope_agents.tools.mcp_client import McpToolClient
from support_ope_agents.tools.registry import ToolRegistry, ToolSpec


class McpToolClientTests(unittest.TestCase):
    def test_tool_spec_populates_missing_handler_docstring_from_description(self) -> None:
        def _handler() -> str:
            return "ok"

        spec = ToolSpec(name="example", description="Example tool description.", handler=_handler)

        self.assertEqual(spec.handler.__doc__, "Example tool description.")

    def test_build_handler_merges_static_and_mapped_arguments(self) -> None:
        client = McpToolClient(McpManifest(path=Path("manifest.json"), servers={}))

        async def _fake_call(server_name: str, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.assertEqual(server_name, "github")
            self.assertEqual(tool_name, "get_issue")
            return arguments

        with patch.object(client, "_call_tool_async", side_effect=_fake_call):
            handler = client.build_handler(
                McpToolBinding(server="github", tool="get_issue"),
                logical_tool_name="external_ticket",
                static_arguments={"owner": "acme", "repo": "external-support"},
                argument_map={"ticket_id": "issue_number"},
                integer_arguments=("issue_number",),
            )
            result = asyncio.run(handler(ticket_id="123"))

        self.assertEqual(
            json.loads(result),
            {"owner": "acme", "repo": "external-support", "issue_number": 123},
        )

    def test_build_handler_rejects_non_numeric_integer_argument(self) -> None:
        client = McpToolClient(McpManifest(path=Path("manifest.json"), servers={}))
        handler = client.build_handler(
            McpToolBinding(server="github", tool="get_issue"),
            logical_tool_name="external_ticket",
            argument_map={"ticket_id": "issue_number"},
            integer_arguments=("issue_number",),
        )

        with self.assertRaisesRegex(ValueError, "requires integer argument 'issue_number'"):
            asyncio.run(handler(ticket_id="issue-123"))

    def test_validate_logical_tool_accepts_server_only_ticket_binding(self) -> None:
        manifest = McpManifest(
            path=Path("manifest.json"),
            servers={
                "github": McpServerConfig(name="github", transport="stdio", command="github-mcp-server"),
            },
        )
        client = McpToolClient(manifest)

        with patch.object(client, "list_tools", return_value=()):
            client.validate_logical_tool(
                logical_tool_name="external_ticket",
                binding=McpToolBinding(server="github", tool=""),
            )

    def test_registry_keeps_server_only_ticket_binding_as_dedicated_workflow_tool(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
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
                        }
                    },
                },
                "agents": {},
            }
        )

        class _FakeMcpClient:
            def validate_logical_tool(self, *, logical_tool_name: str, binding) -> None:
                raise AssertionError(f"unexpected validate_logical_tool call for {logical_tool_name}:{binding}")

            def build_handler(self, *args, **kwargs):
                raise AssertionError("unexpected build_handler call for server-only ticket binding")

        registry = ToolRegistry(config, mcp_tool_client=_FakeMcpClient())

        intake_tools = {tool.name: tool for tool in registry.get_tools("IntakeAgent")}
        self.assertIn("external_ticket", intake_tools)
        self.assertEqual(intake_tools["external_ticket"].provider, "mcp:github")
        self.assertIsNone(intake_tools["external_ticket"].target)
        self.assertIn("not configured", str(intake_tools["external_ticket"].handler()))

    def test_registry_creates_mcp_client_from_config_when_needed(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
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
                        }
                    },
                },
                "agents": {},
            }
        )

        class _FakeMcpClient:
            def validate_logical_tool(self, *, logical_tool_name: str, binding) -> None:
                return None

        with patch("support_ope_agents.tools.registry.McpToolClient.from_config", return_value=_FakeMcpClient()) as from_config:
            ToolRegistry(config)

        from_config.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()