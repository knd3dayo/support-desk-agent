from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from support_desk_agent.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_desk_agent.config import load_config
from support_desk_agent.config.models import AgentCatalogSettings, AppConfig
from support_desk_agent.runtime.sample.sample_service import build_runtime_context
from support_desk_agent.tools import ToolConfigurationError


class SampleConfigTests(unittest.TestCase):
    def test_support_desk_agent_sample_uses_sample_runtime_mode(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "support-desk-agent" / "config-sample.yml"
        loaded = load_config(config_path)

        self.assertEqual(loaded.runtime.mode, "sample")

    def test_support_desk_agent_sample_uses_default_constraint_mode_by_default(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "support-desk-agent" / "config-sample.yml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        settings = AgentCatalogSettings.model_validate(raw["support_desk_agent"]["agents"])

        self.assertEqual(settings.default_constraint_mode, "default")
        self.assertEqual(settings.resolve_constraint_mode(INVESTIGATE_AGENT), "default")
        self.assertEqual(settings.resolve_constraint_mode(SUPERVISOR_AGENT), "default")

    def test_support_desk_agent_sample_configures_github_ticket_logical_tools(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "support-desk-agent" / "config-sample.yml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        logical_tools = raw["support_desk_agent"]["tools"]["logical_tools"]
        external_ticket = logical_tools["external_ticket"]
        internal_ticket = logical_tools["internal_ticket"]

        self.assertEqual(external_ticket["server"], "github")
        self.assertEqual(internal_ticket["server"], "github")
        self.assertIn("repo", external_ticket["arguments"])
        self.assertIn("repo", internal_ticket["arguments"])
        self.assertEqual(external_ticket["candidate_matching"]["candidate_id_fields"], ["number", "issue_number", "id", "key"])
        self.assertEqual(internal_ticket["candidate_matching"]["min_combined_similarity"], 0.35)

    def test_load_config_allows_env_override_for_llm_model_and_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_desk_agent:",
                        "  llm:",
                        "    provider: openai",
                        "    model: poc-chat-model",
                        "    api_key: os.environ/LLM_API_KEY",
                        "    base_url: http://localhost:4000",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "LLM_API_KEY": "sk-test-value",
                    "SUPPORT_OPE_LLM_MODEL": "gpt-4.1",
                    "SUPPORT_OPE_LLM_BASE_URL": "",
                },
                clear=False,
            ):
                loaded = load_config(config_path)

        self.assertEqual(loaded.llm.model, "gpt-4.1")
        self.assertIsNone(loaded.llm.base_url)

    def test_load_config_accepts_attachment_ignore_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_desk_agent:",
                        "  llm:",
                        "    provider: openai",
                        "    model: gpt-4.1",
                        "    api_key: sk-test-value",
                        "  config_paths: {}",
                        "  data_paths:",
                        "    attachment_ignore_patterns:",
                        "      - '*.tmp'",
                        "      - '.evidence/private/**'",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = load_config(config_path)

        self.assertEqual(loaded.data_paths.attachment_ignore_patterns, ["*.tmp", ".evidence/private/**"])

    def test_app_config_accepts_server_only_mcp_ticket_logical_tool(self) -> None:
        loaded = AppConfig.model_validate(
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
                            "server": "generic-ticket-server",
                        }
                    },
                },
                "agents": {},
            }
        )

        external_ticket = loaded.tools.get_logical_tool("external_ticket")
        self.assertIsNotNone(external_ticket)
        self.assertEqual(external_ticket.provider, "mcp")
        self.assertEqual(external_ticket.server, "generic-ticket-server")
        self.assertIsNone(external_ticket.tool)

    def test_load_config_migrates_legacy_ticket_sources_into_logical_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_desk_agent:",
                        "  llm:",
                        "    provider: openai",
                        "    model: gpt-4.1",
                        "    api_key: sk-test-value",
                        "  tools:",
                        "    mcp_manifest_path: ./mcp.json",
                        "    ticket_sources:",
                        "      external:",
                        "        enabled: true",
                        "        server: github",
                        "        description: legacy external binding",
                        "        arguments:",
                        "          repo: external-support",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = load_config(config_path)

        external_ticket = loaded.tools.get_logical_tool("external_ticket")
        self.assertIsNotNone(external_ticket)
        self.assertEqual(external_ticket.provider, "mcp")
        self.assertEqual(external_ticket.server, "github")
        self.assertEqual(external_ticket.arguments, {"repo": "external-support"})
        self.assertEqual(external_ticket.candidate_matching.max_question_candidates, 3)

    def test_load_config_requires_support_desk_agent_root_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "llm:",
                        "  provider: openai",
                        "  model: gpt-4.1",
                        "  api_key: sk-test-value",
                        "tools: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "config root 'support_desk_agent' is required"):
                load_config(config_path)

    def test_sample_runtime_context_validates_enabled_ticket_sources_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_desk_agent:",
                        "  llm:",
                        "    provider: openai",
                        "    model: gpt-4.1",
                        "    api_key: sk-test-value",
                        "  runtime:",
                        "    mode: sample",
                        "  tools:",
                        "    mcp_manifest_path: ./mcp.json",
                        "    ticket_sources:",
                        "      external:",
                        "        enabled: true",
                        "        server: github",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            class _FakeMcpClient:
                def __init__(self) -> None:
                    self.calls: list[str] = []

                def validate_ticket_source(self, *, ticket_kind: str, server_name: str) -> None:
                    self.calls.append(f"{ticket_kind}:{server_name}")

                def validate_logical_tool(self, *, logical_tool_name: str, binding) -> None:
                    return None

            fake_client = _FakeMcpClient()

            with patch(
                "support_desk_agent.runtime.sample.sample_service.McpToolClient.from_config",
                return_value=fake_client,
            ):
                build_runtime_context(str(config_path))

        self.assertEqual(fake_client.calls, ["external:github"])

    def test_sample_runtime_context_fails_fast_when_ticket_source_startup_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_desk_agent:",
                        "  llm:",
                        "    provider: openai",
                        "    model: gpt-4.1",
                        "    api_key: sk-test-value",
                        "  runtime:",
                        "    mode: sample",
                        "  tools:",
                        "    mcp_manifest_path: ./mcp.json",
                        "    ticket_sources:",
                        "      external:",
                        "        enabled: true",
                        "        server: github",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            class _FailingMcpClient:
                def validate_logical_tool(self, *, logical_tool_name: str, binding) -> None:
                    return None

                def validate_ticket_source(self, *, ticket_kind: str, server_name: str) -> None:
                    raise ToolConfigurationError(
                        f"tools.logical_tools.{ticket_kind}_ticket failed startup MCP connectivity check for server '{server_name}': boom"
                    )

            with patch(
                "support_desk_agent.runtime.sample.sample_service.McpToolClient.from_config",
                return_value=_FailingMcpClient(),
            ):
                with self.assertRaisesRegex(ToolConfigurationError, "tools.logical_tools.external_ticket"):
                    build_runtime_context(str(config_path))


if __name__ == "__main__":
    unittest.main()