from __future__ import annotations

import json
import unittest
from pathlib import Path

from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_search_documents import build_default_search_documents_tool


REPO_ROOT = Path("/home/user/source/repos")


class KnowledgeRetrieverTests(unittest.TestCase):
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

        self.assertIn("ai-platform-poc", result["knowledge_retrieval_adopted_sources"])
        source_results = [
            item for item in result["knowledge_retrieval_results"] if item.get("source_name") == "ai-platform-poc"
        ]
        self.assertEqual(len(source_results), 1)
        source_result = source_results[0]
        self.assertEqual(source_result["status"], "matched")
        self.assertTrue(source_result["matched_paths"])
        self.assertIn("/knowledge/ai-platform-poc/README.md", source_result["matched_paths"])
        self.assertTrue(source_result["evidence"])
        self.assertIn("Application層", source_result["summary"])
        self.assertIn("AIガバナンス層", source_result["summary"])


if __name__ == "__main__":
    unittest.main()