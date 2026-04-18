from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.agents.production.investigate_agent import InvestigateAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool


class ConsolidatedDraftTests(unittest.TestCase):
    def _build_config(self) -> AppConfig:
        return AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

    def test_consolidated_investigate_builds_specification_draft(self) -> None:
        config = self._build_config()
        agent = InvestigateAgent(
            config=config,
            search_documents_tool=lambda **_: '{"results":[{"source_name":"ai-chat-util","source_type":"document_source","status":"matched","summary":"ai-chat-util は生成AI向けユーティリティです。","matched_paths":["/knowledge/ai-chat-util/README.md"],"evidence":["チャット支援機能を提供します"]}]}',
        )

        result = agent.execute(
            {
                "workflow_kind": "specification_inquiry",
                "raw_issue": "ai-chat-util について教えて",
            }
        )

        draft = str(result.get("draft_response") or "")
        self.assertIn("結論:", draft)
        self.assertIn("概要レベルの確認結果:", draft)
        self.assertIn("次アクション:", draft)
        self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-chat-util")

    def test_consolidated_investigate_builds_incident_draft(self) -> None:
        config = self._build_config()
        agent = InvestigateAgent(
            config=config,
            detect_log_format_tool=lambda *_args, **_kwargs: '{"detected_format":"unknown","search_results":{"severity":[{"line_number":9,"line":"2026-04-10 ERROR Data source vdpcachedatasource not found"}],"java_exception":[{"line_number":10,"line":"com.denodo.vdb.cache.VDBCacheException: Data source vdpcachedatasource not found"}]}}',
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text("sample\n", encoding="utf-8")
            result = agent.execute(
                {
                    "workflow_kind": "incident_investigation",
                    "workspace_path": tmpdir,
                    "raw_issue": "vdp.log の障害を調査してください",
                }
            )

        draft = str(result.get("draft_response") or "")
        self.assertIn("結論:", draft)
        self.assertIn("原因候補:", draft)
        self.assertIn("次アクション:", draft)
        self.assertIn("vdpcachedatasource", draft)

    def test_consolidated_investigate_writes_generated_draft(self) -> None:
        config = self._build_config()
        write_draft_tool = build_default_write_draft_tool(config, "customer_response_draft")
        agent = InvestigateAgent(
            config=config,
            search_documents_tool=lambda **_: '{"results":[{"source_name":"sample","source_type":"document_source","status":"matched","summary":"sample の概要です。","matched_paths":["/knowledge/sample/README.md"],"evidence":["sample の概要です。"]}]}',
            write_draft_tool=write_draft_tool,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent.execute(
                {
                    "case_id": "CASE-TEST-DRAFT-001",
                    "workspace_path": tmpdir,
                    "workflow_kind": "specification_inquiry",
                    "raw_issue": "sample の概要を教えて",
                }
            )
            draft_path = Path(tmpdir) / ".artifacts" / "drafts" / "customer_response_draft.md"

            self.assertTrue(draft_path.exists())
            self.assertIn("結論:", draft_path.read_text(encoding="utf-8"))
            self.assertIn("結論:", str(result.get("draft_response") or ""))

    def test_consolidated_investigate_preserves_existing_draft(self) -> None:
        config = self._build_config()
        agent = InvestigateAgent(config=config)

        result = agent.execute(
            {
                "workflow_kind": "specification_inquiry",
                "raw_issue": "sample の概要を教えて",
                "draft_response": "既存ドラフト",
            }
        )

        self.assertEqual(str(result.get("draft_response") or ""), "既存ドラフト")


if __name__ == "__main__":
    unittest.main()
