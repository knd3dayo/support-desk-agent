from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool


class _FakeDraftModel:
    def __init__(self, content: str):
        self._content = content

    async def ainvoke(self, _messages):
        return AIMessage(content=self._content)


class DraftWriterTests(unittest.TestCase):
    def test_draft_writer_does_not_append_compliance_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "notice": {
                                "required": True,
                                "required_phrases": ["この回答は生成AI補助を含み、誤りの可能性があります"],
                            }
                        }
                    },
                }
            )
            executor = DraftWriterPhaseExecutor(
                config=config,
                write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
            )

            with patch(
                "support_ope_agents.agents.draft_writer_agent._get_chat_model",
                return_value=_FakeDraftModel("お問い合わせありがとうございます。\n\n現時点では仕様上の動作と判断しています。"),
            ):
                result = executor.execute(
                    {
                        "case_id": "CASE-TEST-008",
                        "workspace_path": str(workspace_path),
                        "investigation_summary": "現時点では仕様上の動作と判断しています。",
                        "review_focus": "誤解を招かない表現にする",
                    }
                )

            draft = str(result.get("draft_response") or "")
            self.assertNotIn("この回答は生成AI補助を含み、誤りの可能性があります", draft)
            self.assertNotIn("【注意事項】", draft)
            self.assertIn("お問い合わせありがとうございます。", draft)

    def test_draft_writer_hides_internal_compliance_revision_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "notice": {
                                "required": True,
                                "required_phrases": ["生成AIは誤った回答をすることがあります"],
                            }
                        }
                    },
                }
            )
            executor = DraftWriterPhaseExecutor(
                config=config,
                write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
            )

            with patch(
                "support_ope_agents.agents.draft_writer_agent._get_chat_model",
                return_value=_FakeDraftModel(
                    "確認根拠となるポリシー文書を取得できませんでした。document_sources の設定と配置を確認してください。\n\n回避策候補をご案内します。"
                ),
            ):
                result = executor.execute(
                    {
                        "case_id": "CASE-TEST-009",
                        "workspace_path": str(workspace_path),
                        "investigation_summary": "現時点では既知事例と一致するため、回避策候補をご案内します。",
                        "compliance_revision_request": "確認根拠となるポリシー文書を取得できませんでした。document_sources の設定と配置を確認してください。",
                    }
                )

            draft = str(result.get("draft_response") or "")
            self.assertNotIn("ポリシー文書", draft)
            self.assertNotIn("document_sources", draft)
            self.assertIn("回避策候補", draft)

    def test_draft_writer_bypass_preserves_runtime_filtered_text(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "DraftWriterAgent": {
                        "constraint_mode": "bypass",
                    }
                },
            }
        )
        executor = DraftWriterPhaseExecutor(
            config=config,
            write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
        )

        result = executor.execute(
            {
                "draft_response": "SuperVisorAgent が関連資料を確認しました。\n\nquery: internal",
            }
        )

        draft = str(result.get("draft_response") or "")
        self.assertIn("SuperVisorAgent", draft)
        self.assertIn("query: internal", draft)

    def test_draft_writer_default_mode_preserves_findings_while_replacing_internal_terms(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        executor = DraftWriterPhaseExecutor(
            config=config,
            write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
        )

        result = executor.execute(
            {
                "draft_response": "LogAnalyzerAgent が vdp.log を解析し、Query: Denodo 障害 について com.denodo.vdb.cache.VDBCacheException を確認しました。",
            }
        )

        draft = str(result.get("draft_response") or "")
        self.assertIn("ログ解析 が vdp.log を解析", draft)
        self.assertIn("問い合わせ内容:", draft)
        self.assertIn("com.denodo.vdb.cache.VDBCacheException", draft)
        self.assertNotIn("関連資料を確認し、現時点で把握できている内容を整理しました。", draft)

    def test_draft_writer_adds_support_outline_for_incident_investigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {},
                }
            )
            executor = DraftWriterPhaseExecutor(
                config=config,
                write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
            )

            with patch(
                "support_ope_agents.agents.draft_writer_agent._get_chat_model",
                return_value=_FakeDraftModel("vdp.log の解析結果として例外候補を確認しました。"),
            ):
                result = executor.execute(
                    {
                        "case_id": "CASE-TEST-INCIDENT-OUTLINE-001",
                        "workspace_path": str(workspace_path),
                        "workflow_kind": "incident_investigation",
                        "investigation_summary": (
                            "vdp.log を解析し、com.denodo.vdb.cache.VDBCacheException を確認しました。"
                            "代表的な例外行: L9: com.denodo.vdb.cache.VDBCacheException: Data source vdpcachedatasource not found。"
                        ),
                    }
                )

            draft = str(result.get("draft_response") or "")
            self.assertIn("結論:", draft)
            self.assertIn("原因候補:", draft)
            self.assertIn("次アクション:", draft)
            self.assertIn("Data source vdpcachedatasource not found", draft)


if __name__ == "__main__":
    unittest.main()