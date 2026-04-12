from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from pydantic import ValidationError

from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_search_documents import build_default_search_documents_tool
from support_ope_agents.tools.registry import ToolRegistry


REPO_ROOT = Path("/home/user/source/repos")


class KnowledgeRetrieverTests(unittest.TestCase):
    def test_incident_summary_suppresses_unrelated_generic_highlight(self) -> None:
        executor = KnowledgeRetrieverPhaseExecutor(
            search_documents_tool=lambda **_: json.dumps(
                {
                    "message": "document_sources から関連箇所を抽出しました。",
                    "results": [
                        {
                            "source_name": "ai-platform-poc",
                            "source_description": "生成AI基盤のアーキテクチャ検討資料",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "ai-platform-poc は生成AI基盤 PoC 全体を説明します。",
                            "path": "/tmp/ai-platform-poc",
                            "route_prefix": "/knowledge/ai-platform-poc/",
                            "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                            "evidence": ["アーキテクチャの考え方"],
                            "feature_bullets": [") -> Set[AdditionalLoggingUtils]"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            external_ticket_tool=lambda: "external_ticket tool is not configured.",
            internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
        )

        result = executor.execute(
            {
                "raw_issue": "添付したファイルはDenodoのvdp.logです。エラー調査をお願いします Data source vdpcachedatasource not found",
                "workflow_kind": "incident_investigation",
            }
        )

        retrieval_summary = cast(str, result["knowledge_retrieval_summary"])
        self.assertIn("障害調査の補助として関連資料を確認しました", retrieval_summary)
        self.assertIn("直接的な障害原因を裏付ける資料は見つかりませんでした", retrieval_summary)
        self.assertNotIn("AdditionalLoggingUtils", retrieval_summary)

    def test_instruction_only_and_bypass_preserve_raw_incident_style_summary(self) -> None:
        for constraint_mode in ("instruction_only", "bypass"):
            executor = KnowledgeRetrieverPhaseExecutor(
                search_documents_tool=lambda **_: json.dumps(
                    {
                        "message": "document_sources から関連箇所を抽出しました。",
                        "results": [
                            {
                                "source_name": "ai-platform-poc",
                                "source_description": "生成AI基盤のアーキテクチャ検討資料",
                                "source_type": "document_source",
                                "status": "matched",
                                "summary": "ai-platform-poc は生成AI基盤 PoC 全体を説明します。",
                                "path": "/tmp/ai-platform-poc",
                                "route_prefix": "/knowledge/ai-platform-poc/",
                                "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                                "evidence": ["アーキテクチャの考え方"],
                                "feature_bullets": [") -> Set[AdditionalLoggingUtils]"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                external_ticket_tool=lambda: "external_ticket tool is not configured.",
                internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
                constraint_mode=constraint_mode,
            )

            result = executor.execute(
                {
                    "raw_issue": "添付したファイルはDenodoのvdp.logです。エラー調査をお願いします Data source vdpcachedatasource not found",
                    "workflow_kind": "incident_investigation",
                }
            )

            retrieval_summary = cast(str, result["knowledge_retrieval_summary"])
            self.assertIn("問い合わせ内容をもとに document_sources を検索しました", retrieval_summary)
            self.assertIn("AdditionalLoggingUtils", retrieval_summary)
            self.assertNotIn("障害調査の補助として関連資料を確認しました", retrieval_summary)

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
                "llm": {"provider": "openai", "model": "poc-chat-model", "api_key": "sk-test-value", "base_url": "http://localhost:4000"},
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

    def test_removed_knowledge_retriever_search_settings_are_rejected(self) -> None:
        for removed_key, removed_value in [
            ("search_keywords", []),
            ("search_keyword_expansion_enabled", True),
            ("feature_bullet_max_items", 5),
            ("feature_heading_keywords", ["features"]),
            ("raw_backend_max_matches", 50),
            ("ignore_patterns", [".*"]),
            ("ignore_patterns_file", "./.support-ope-ignore"),
        ]:
            with self.subTest(removed_key=removed_key):
                with self.assertRaises(ValidationError):
                    AppConfig.model_validate(
                        {
                            "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                            "config_paths": {},
                            "data_paths": {},
                            "agents": {
                                "KnowledgeRetrieverAgent": {
                                    "document_sources": [{"name": "docs", "description": "test docs", "path": "/tmp/docs"}],
                                    removed_key: removed_value,
                                }
                            },
                            "interfaces": {},
                        }
                    )

    def test_limited_extraction_mode_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "agents": {
                        "KnowledgeRetrieverAgent": {
                            "document_sources": [{"name": "docs", "description": "test docs", "path": "/tmp/docs"}],
                            "extraction_mode": "limited",
                        }
                    },
                    "interfaces": {},
                }
            )

    def test_ai_platform_poc_returns_architecture_overview(self) -> None:
        source_path = REPO_ROOT / "ai-platform-poc"
        self.assertTrue(source_path.exists(), "ai-platform-poc repository is required for this test")

        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "agents": {"KnowledgeRetrieverAgent": {"document_sources": [{"name": "ai-platform-poc", "description": "生成AI基盤のアーキテクチャ検討資料", "path": str(source_path)}]}},
                "interfaces": {},
            }
        )
        executor = KnowledgeRetrieverPhaseExecutor(
            search_documents_tool=build_default_search_documents_tool(config),
            external_ticket_tool=lambda: "external_ticket tool is not configured.",
            internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
        )
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
        self.assertIn("業務適用を見据えた生成AI基盤の PoC リポジトリです", summary)
        retrieval_summary = cast(str, result["knowledge_retrieval_summary"])
        self.assertIn("検索しました", retrieval_summary)
        self.assertIn("生成AI基盤のアーキテクチャの概要を返してください", retrieval_summary)
        self.assertIn("採用した根拠ソース: ai-platform-poc", retrieval_summary)

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

    def test_prioritizes_explicitly_named_document_source(self) -> None:
        executor = KnowledgeRetrieverPhaseExecutor(
            search_documents_tool=lambda **_: json.dumps(
                {
                    "message": "document_sources から関連箇所を抽出しました。",
                    "results": [
                        {
                            "source_name": "ai-platform-poc",
                            "source_description": "生成AI基盤のアーキテクチャ検討資料",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "ai-platform-poc は生成AI基盤 PoC 全体を説明します。",
                            "path": "/tmp/ai-platform-poc",
                            "route_prefix": "/knowledge/ai-platform-poc/",
                            "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                            "evidence": ["生成AI", "基盤", "PoC"],
                        },
                        {
                            "source_name": "ai-chat-util",
                            "source_description": "チャットユーティリティの利用資料",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "ai-chat-util は利用可能な機能と API をまとめた資料です。",
                            "path": "/tmp/ai-chat-util",
                            "route_prefix": "/knowledge/ai-chat-util/",
                            "matched_paths": ["/knowledge/ai-chat-util/README.md"],
                            "evidence": ["機能一覧"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            external_ticket_tool=lambda: "external_ticket tool is not configured.",
            internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
        )

        result = executor.execute({"raw_issue": "ai-chat-utilの機能一覧を出して"})

        document_results = [
            item
            for item in cast(list[dict[str, object]], result["knowledge_retrieval_results"])
            if item.get("source_type") == "document_source"
        ]
        self.assertEqual(document_results[0]["source_name"], "ai-chat-util")
        self.assertEqual(cast(list[str], result["knowledge_retrieval_adopted_sources"])[0], "ai-chat-util")
        retrieval_summary = cast(str, result["knowledge_retrieval_summary"])
        self.assertIn("代表ソース: ai-chat-util。", retrieval_summary)
        self.assertIn("要点: 機能一覧", retrieval_summary)

    def test_extracts_feature_bullets_for_feature_list_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            readme = root / "README.md"
            readme.write_text(
                "# sample\n\n概要です。\n\n## できること\n\n- テキストチャットを LLM に送る\n- Excel 入力でバッチ処理を回す\n- MCP サーバーとしてツール提供する\n",
                encoding="utf-8",
            )

            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "agents": {"KnowledgeRetrieverAgent": {"document_sources": [{"name": "sample", "description": "sample docs", "path": str(root)}]}},
                    "interfaces": {},
                }
            )
            executor = KnowledgeRetrieverPhaseExecutor(
                search_documents_tool=build_default_search_documents_tool(config),
                external_ticket_tool=lambda: "external_ticket tool is not configured.",
                internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
            )
            with patch(
                "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
                return_value={
                    "sample": {
                        "source_name": "sample",
                        "status": "matched",
                        "summary": "概要です。",
                        "matched_paths": ["/knowledge/sample/README.md"],
                        "evidence": ["概要です。"],
                        "feature_bullets": [
                            "テキストチャットを LLM に送る",
                            "Excel 入力でバッチ処理を回す",
                            "MCP サーバーとしてツール提供する",
                        ],
                        "raw_content": "",
                    }
                },
            ):
                result = executor.execute({"raw_issue": "sampleの機能一覧を出して"})

            source_result = next(
                item for item in cast(list[dict[str, object]], result["knowledge_retrieval_results"]) if item.get("source_name") == "sample"
            )
            self.assertEqual(
                cast(list[str], source_result["feature_bullets"]),
                ["テキストチャットを LLM に送る", "Excel 入力でバッチ処理を回す", "MCP サーバーとしてツール提供する"],
            )

    def test_writes_raw_backend_like_results_to_working_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            source_root = workspace_path / "docs"
            source_root.mkdir()
            (source_root / "README.md").write_text(
                "# sample\n\n概要です。\n\n## できること\n\n- テキストチャットを LLM に送る\n",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "agents": {"KnowledgeRetrieverAgent": {"document_sources": [{"name": "sample", "description": "sample docs", "path": str(source_root)}]}},
                    "interfaces": {},
                }
            )
            executor = KnowledgeRetrieverPhaseExecutor(
                search_documents_tool=build_default_search_documents_tool(config),
                external_ticket_tool=lambda: "external_ticket tool is not configured.",
                internal_ticket_tool=lambda: "internal_ticket tool is not configured.",
                write_working_memory_tool=ToolRegistry(config).get_tools("KnowledgeRetrieverAgent")[-1].handler,
            )
            with patch(
                "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
                return_value={
                    "sample": {
                        "source_name": "sample",
                        "status": "matched",
                        "summary": "概要です。",
                        "matched_paths": ["/knowledge/sample/README.md"],
                        "evidence": ["概要です。"],
                        "feature_bullets": ["テキストチャットを LLM に送る"],
                        "raw_content": "",
                    }
                },
            ):
                executor.execute(
                    {
                        "case_id": "CASE-TEST-WM-001",
                        "workspace_path": str(workspace_path),
                        "raw_issue": "sampleの機能一覧を出して",
                    }
                )

            working_path = workspace_path / ".memory" / "agents" / "KnowledgeRetrieverAgent" / "working.md"
            content = working_path.read_text(encoding="utf-8")
            self.assertIn("## Result: sample", content)
            self.assertIn("Raw result:", content)
            self.assertIn('"source_name": "sample"', content)

    def test_search_documents_raw_backend_mode_includes_backend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            readme = root / "README.md"
            readme.write_text(
                "# sample\n\n概要です。\n\n## できること\n\n- テキストチャットを LLM に送る\n",
                encoding="utf-8",
            )

            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "agents": {
                        "KnowledgeRetrieverAgent": {
                            "document_sources": [{"name": "sample", "description": "sample docs", "path": str(root)}],
                            "extraction_mode": "raw_backend",
                        }
                    },
                    "interfaces": {},
                }
            )

            with patch(
                "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
                return_value={
                    "sample": {
                        "source_name": "sample",
                        "status": "matched",
                        "summary": "# sample\n\n概要です。",
                        "matched_paths": ["/knowledge/sample/README.md"],
                        "evidence": ["概要です。"],
                        "feature_bullets": [],
                        "raw_content": "# sample\n\n概要です。\n\n## できること\n\n- テキストチャットを LLM に送る\n",
                    }
                },
            ):
                parsed = json.loads(build_default_search_documents_tool(config)(query="sampleの機能一覧を出して"))

            source_result = parsed["results"][0]
            self.assertIn("raw_backend", source_result)
            self.assertEqual(source_result["raw_backend"]["mode"], "raw_backend")
            self.assertIn("file_data", source_result["raw_backend"])
            self.assertIn("概要です", source_result["raw_backend"]["file_data"]["content"])

    def test_search_documents_uses_deepagents_result_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            readme = root / "README.md"
            readme.write_text(
                "# sample\n\nこの資料はユーティリティ群の説明です。\n",
                encoding="utf-8",
            )

            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "agents": {
                        "KnowledgeRetrieverAgent": {
                            "document_sources": [{"name": "sample", "description": "sample docs", "path": str(root)}],
                            "extraction_mode": "relaxed",
                        }
                    },
                    "interfaces": {},
                }
            )

            with patch(
                "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
                return_value={
                    "sample": {
                        "source_name": "sample",
                        "status": "matched",
                        "summary": "この資料はユーティリティ群の説明です。",
                        "matched_paths": ["/knowledge/sample/README.md"],
                        "evidence": ["この資料はユーティリティ群の説明です。"],
                        "feature_bullets": ["ユーティリティを提供する"],
                        "raw_content": "",
                    }
                },
            ):
                parsed = json.loads(build_default_search_documents_tool(config)(query="sampleの詳細を教えて"))

            source_result = parsed["results"][0]
            self.assertIn("ユーティリティ群の説明です。", source_result["evidence"][0])
            self.assertEqual(source_result["feature_bullets"], ["ユーティリティを提供する"])


if __name__ == "__main__":
    unittest.main()