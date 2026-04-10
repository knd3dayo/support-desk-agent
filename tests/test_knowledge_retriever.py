from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_search_documents import build_default_search_documents_tool
from support_ope_agents.tools.registry import ToolRegistry


REPO_ROOT = Path("/home/user/source/repos")


class KnowledgeRetrieverTests(unittest.TestCase):
    def test_old_ticket_source_config_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "dummy", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "knowledge_retrieval": {
                        "external_ticket": {
                            "description": "external ticket",
                            "mcp_server": "support-ticket-mcp",
                            "mcp_tool": "get_external_ticket",
                        },
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_enabled_mcp_logical_tool_requires_manifest(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "dummy", "base_url": "http://localhost:4000"},
                    "config_paths": {},
                    "data_paths": {},
                    "tools": {
                        "logical_tools": {
                            "external_ticket": {
                                "enabled": True,
                                "provider": "mcp",
                                "server": "support-ticket-mcp",
                                "tool": "get_external_ticket",
                            }
                        }
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_registry_keeps_ticket_tools_available_without_logical_tool_config(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "dummy", "base_url": "http://localhost:4000"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        registry = ToolRegistry(config)

        tools = {tool.name: tool for tool in registry.get_tools("KnowledgeRetrieverAgent")}
        self.assertEqual(tools["external_ticket"].provider, "local")
        self.assertEqual(tools["internal_ticket"].provider, "local")

    def test_returns_unavailable_when_document_sources_are_missing(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
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

    def test_search_documents_ignores_default_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ignored_doc = root / "node_modules" / "README.md"
            kept_doc = root / "docs" / "overview.md"
            ignored_doc.parent.mkdir(parents=True, exist_ok=True)
            kept_doc.parent.mkdir(parents=True, exist_ok=True)
            ignored_doc.write_text("ignored node_modules document", encoding="utf-8")
            kept_doc.write_text("overview\n\n生成AI基盤の概要です。十分な長さの説明文をここに置きます。", encoding="utf-8")

            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "knowledge_retrieval": {
                        "document_sources": [
                            {
                                "name": "docs",
                                "description": "test docs",
                                "path": str(root),
                            }
                        ]
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

            parsed = json.loads(build_default_search_documents_tool(config)(query="生成AI基盤"))

            source_result = parsed["results"][0]
            self.assertEqual(source_result["status"], "matched")
            self.assertEqual(source_result["matched_paths"][0], "/knowledge/docs/docs/overview.md")

    def test_search_documents_applies_ignore_patterns_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            readme = root / "README.md"
            overview = root / "overview.md"
            ignore_file = root / ".support-ope-ignore"
            readme.write_text("README\n\nこの文書は除外されるべきです。十分な長さの説明文をここに置きます。", encoding="utf-8")
            overview.write_text("overview\n\n生成AI基盤の説明文です。十分な長さの説明文をここに置きます。", encoding="utf-8")
            ignore_file.write_text("README.md\n", encoding="utf-8")

            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "knowledge_retrieval": {
                        "document_sources": [
                            {
                                "name": "docs",
                                "description": "test docs",
                                "path": str(root),
                            }
                        ],
                        "ignore_patterns_file": str(ignore_file),
                    },
                    "interfaces": {},
                    "agents": {},
                }
            )

            parsed = json.loads(build_default_search_documents_tool(config)(query="生成AI基盤"))

            source_result = parsed["results"][0]
            self.assertEqual(source_result["matched_paths"][0], "/knowledge/docs/overview.md")

    def test_ai_platform_poc_returns_architecture_overview(self) -> None:
        source_path = REPO_ROOT / "ai-platform-poc"
        self.assertTrue(source_path.exists(), "ai-platform-poc repository is required for this test")

        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "knowledge_retrieval": {
                    "document_sources": [
                        {
                            "name": "ai-platform-poc",
                            "description": "生成AI基盤のアーキテクチャ検討資料",
                            "path": str(source_path),
                        }
                    ]
                },
                "interfaces": {},
                "agents": {},
            }
        )
        executor = KnowledgeRetrieverPhaseExecutor(
            search_documents_tool=build_default_search_documents_tool(config),
            external_ticket_tool=lambda: "external_ticket tool is not configured.",
            internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
        )

        result = executor.execute({"raw_issue": "生成AI基盤のアーキテクチャの概要を返してください"})

        adopted_sources = cast(list[str], result["knowledge_retrieval_adopted_sources"])
        self.assertIn("ai-platform-poc", adopted_sources)
        source_results = [
            item
            for item in cast(list[dict[str, object]], result["knowledge_retrieval_results"])
            if item.get("source_name") == "ai-platform-poc"
        ]
        self.assertEqual(len(source_results), 1)
        source_result = source_results[0]
        self.assertEqual(source_result["status"], "matched")
        matched_paths = cast(list[str], source_result["matched_paths"])
        summary = cast(str, source_result["summary"])
        evidence = cast(list[str], source_result["evidence"])
        self.assertTrue(matched_paths)
        self.assertIn("/knowledge/ai-platform-poc/README.md", matched_paths)
        self.assertTrue(evidence)
        self.assertIn("Application層", summary)
        self.assertIn("AIガバナンス層", summary)

    def test_prefers_intake_hydrated_ticket_context_over_refetch(self) -> None:
        external_calls: list[str] = []
        internal_calls: list[str] = []

        executor = KnowledgeRetrieverPhaseExecutor(
            search_documents_tool=lambda query: json.dumps({"message": "no docs", "results": []}, ensure_ascii=False),
            external_ticket_tool=lambda **kwargs: external_calls.append(str(kwargs.get("ticket_id") or "")) or "external refetch",
            internal_ticket_tool=lambda **kwargs: internal_calls.append(str(kwargs.get("ticket_id") or "")) or "internal refetch",
        )

        result = executor.execute(
            {
                "raw_issue": "ticket を確認したい",
                "external_ticket_id": "EXT-001",
                "internal_ticket_id": "INT-001",
                "external_ticket_lookup_enabled": True,
                "internal_ticket_lookup_enabled": True,
                "intake_ticket_context_summary": {
                    "external_ticket": "external summary",
                    "internal_ticket": "internal summary",
                },
                "intake_ticket_artifacts": {
                    "external_ticket": ["/tmp/external.json"],
                    "internal_ticket": ["/tmp/internal.json"],
                },
            }
        )

        results = cast(list[dict[str, object]], result["knowledge_retrieval_results"])
        external_result = next(item for item in results if item.get("source_name") == "external_ticket")
        internal_result = next(item for item in results if item.get("source_name") == "internal_ticket")
        self.assertEqual(external_result["status"], "hydrated")
        self.assertEqual(internal_result["status"], "hydrated")
        self.assertEqual(external_calls, [])
        self.assertEqual(internal_calls, [])


if __name__ == "__main__":
    unittest.main()