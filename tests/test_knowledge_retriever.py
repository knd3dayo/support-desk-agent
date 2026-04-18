from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from support_ope_agents.agents.production.investigate_agent import InvestigateAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_search_documents import build_default_search_documents_tool
from support_ope_agents.tools.registry import ToolRegistry


REPO_ROOT = Path("/home/user/source/repos")


class ConsolidatedKnowledgeTests(unittest.TestCase):
    def test_old_ticket_source_config_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "knowledge_retrieval": {
                        "external_ticket": {
                            "description": "external ticket",
                            "mcp_server": "support-ticket-mcp",
                            "mcp_tool": "get_external_ticket",
                        }
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_old_top_level_knowledge_retrieval_config_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "knowledge_retrieval": {
                        "document_sources": [
                            {"name": "docs", "description": "test docs", "path": "/tmp/docs"}
                        ]
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_enabled_mcp_logical_tool_requires_manifest(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "tools": {
                        "logical_tools": {
                            "classify_ticket": {
                                "enabled": True,
                                "provider": "mcp",
                                "server": "support-ticket-mcp",
                                "tool": "classify_ticket",
                            }
                        }
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_enabled_ticket_source_requires_manifest(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "tools": {
                        "ticket_sources": {
                            "external": {
                                "enabled": True,
                                "server": "support-ticket-mcp",
                            }
                        }
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_legacy_ticket_logical_tool_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "tools": {
                        "mcp_manifest_path": "/tmp/test-mcp.json",
                        "logical_tools": {
                            "external_ticket": {
                                "enabled": True,
                                "provider": "mcp",
                                "server": "support-ticket-mcp",
                                "tool": "get_external_ticket",
                                "arguments": {"owner": "acme", "repo": "support"},
                            }
                        },
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_registry_keeps_ticket_tools_available_without_logical_tool_config(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        registry = ToolRegistry(config)
        tools = {tool.name: tool for tool in registry.get_tools("InvestigateAgent")}

        self.assertEqual(tools["external_ticket"].provider, "local")
        self.assertEqual(tools["internal_ticket"].provider, "local")

    def test_internal_memory_tools_are_rejected_during_config_validation(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "tools": {
                        "logical_tools": {
                            "write_shared_memory": {
                                "enabled": True,
                                "provider": "builtin",
                            }
                        },
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_returns_unavailable_when_document_sources_are_missing(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        tool = build_default_search_documents_tool(config)

        parsed = json.loads(tool(query="生成AI基盤のアーキテクチャ概要"))

        self.assertEqual(parsed["status"], "unavailable")
        self.assertIn("参照可能なドキュメントがないので回答できません", parsed["message"])

    def test_search_documents_raises_when_deepagents_search_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_root = Path(tmpdir) / "docs"
            docs_root.mkdir()
            (docs_root / "readme.md").write_text("# docs\n", encoding="utf-8")
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "InvestigateAgent": {
                            "document_sources": [
                                {"name": "docs", "description": "test docs", "path": str(docs_root)}
                            ]
                        }
                    },
                }
            )

            tool = build_default_search_documents_tool(config)

            with patch(
                "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
                side_effect=ConnectionError("LLM connection failed"),
            ):
                with self.assertRaisesRegex((RuntimeError, ConnectionError), "LLM connection failed|DeepAgents"):
                    tool(query="生成AI基盤のアーキテクチャ概要")

    def test_search_documents_raises_when_deepagents_returns_unstructured_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            docs_root = Path(tmpdir) / "docs"
            docs_root.mkdir()
            (docs_root / "readme.md").write_text("# docs\n", encoding="utf-8")
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "InvestigateAgent": {
                            "document_sources": [
                                {"name": "docs", "description": "test docs", "path": str(docs_root)}
                            ]
                        }
                    },
                }
            )

            tool = build_default_search_documents_tool(config)

            with patch(
                "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
                return_value=None,
            ):
                with self.assertRaisesRegex(RuntimeError, "structured response"):
                    tool(query="生成AI基盤のアーキテクチャ概要")

    def test_consolidated_investigate_builds_knowledge_summary(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        agent = InvestigateAgent(
            config=config,
            search_documents_tool=lambda **_: json.dumps(
                {
                    "results": [
                        {
                            "source_name": "ai-platform-poc",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "業務適用を見据えた生成AI基盤の PoC リポジトリです。",
                            "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                            "evidence": ["業務適用を見据えた生成AI基盤の PoC リポジトリです。"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        )

        result = agent.execute({"raw_issue": "生成AI基盤のアーキテクチャ概要を教えてください。"})

        self.assertIn("ai-platform-poc", str(result.get("knowledge_retrieval_summary") or ""))
        self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-platform-poc")

    def test_consolidated_investigate_prefers_hydrated_ticket_context(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        agent = InvestigateAgent(config=config)

        result = agent.execute(
            {
                "raw_issue": "external_ticket の内容を確認したい",
                "external_ticket_id": "EXT-001",
                "external_ticket_lookup_enabled": True,
                "intake_ticket_context_summary": {"external_ticket": "external summary"},
                "intake_ticket_artifacts": {"external_ticket": ["/tmp/external.json"]},
            }
        )

        results = result.get("knowledge_retrieval_results") or []
        external_result = next(item for item in results if item.get("source_name") == "external_ticket")
        self.assertEqual(str(external_result.get("status") or ""), "hydrated")
        self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "external_ticket")

    def test_ai_platform_poc_search_tool_returns_architecture_overview(self) -> None:
        source_path = REPO_ROOT / "ai-platform-poc"
        self.assertTrue(source_path.exists(), "ai-platform-poc repository is required for this test")

        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "agents": {"InvestigateAgent": {"document_sources": [{"name": "ai-platform-poc", "description": "生成AI基盤のアーキテクチャ検討資料", "path": str(source_path)}]}},
                "interfaces": {},
            }
        )
        tool = build_default_search_documents_tool(config)
        with patch(
            "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
            return_value={
                "ai-platform-poc": {
                    "source_name": "ai-platform-poc",
                    "status": "matched",
                    "summary": "業務適用を見据えた生成AI基盤の PoC リポジトリです。",
                    "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                    "evidence": ["業務適用を見据えた生成AI基盤の PoC リポジトリです。"],
                    "feature_bullets": [],
                    "raw_content": "",
                }
            },
        ):
            parsed = json.loads(tool(query="生成AI基盤のアーキテクチャの概要を返してください"))

        self.assertEqual(parsed["status"], "matched")
        self.assertEqual(parsed["results"][0]["source_name"], "ai-platform-poc")


if __name__ == "__main__":
    unittest.main()
