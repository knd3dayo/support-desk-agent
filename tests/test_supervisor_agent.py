from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_read_shared_memory import build_default_read_shared_memory_tool
from support_ope_agents.tools.default_write_shared_memory import build_default_write_shared_memory_tool


class _FakeKnowledgeRetrieverExecutor:
    @staticmethod
    def execute(_state: dict[str, object]) -> dict[str, object]:
        return {
            "knowledge_retrieval_summary": "2 つのソースから候補を取得しました。",
            "knowledge_retrieval_results": [
                {
                    "source_name": "internal_ticket",
                    "source_type": "ticket_source",
                    "status": "fetched",
                    "summary": "内部票の要約",
                    "matched_paths": [],
                    "evidence": ["ticket evidence"],
                },
                {
                    "source_name": "ai-platform-poc",
                    "source_type": "document_source",
                    "status": "matched",
                    "summary": "生成AI基盤の 3 層構成を説明",
                    "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                    "evidence": ["Application層", "Tool層", "AIガバナンス層"],
                },
            ],
            "knowledge_retrieval_adopted_sources": ["ai-platform-poc"],
        }


class SupervisorAgentTests(unittest.TestCase):
    def test_supervisor_records_final_adopted_knowledge_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {},
                }
            )
            read_shared_memory = build_default_read_shared_memory_tool(config)
            write_shared_memory = build_default_write_shared_memory_tool(config)
            workspace_path = Path(tmpdir)

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                knowledge_retriever_executor=_FakeKnowledgeRetrieverExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-005",
                    "workspace_path": str(workspace_path),
                    "execution_mode": "action",
                    "workflow_kind": "specification_inquiry",
                    "intake_category": "specification_inquiry",
                    "intake_urgency": "medium",
                    "raw_issue": "生成AI基盤のアーキテクチャ概要を確認したい",
                }
            )

            self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-platform-poc")
            self.assertEqual(result.get("knowledge_retrieval_adopted_sources") or [], ["ai-platform-poc"])


if __name__ == "__main__":
    unittest.main()