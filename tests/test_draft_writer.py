from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool


class DraftWriterTests(unittest.TestCase):
    def test_draft_writer_does_not_append_compliance_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
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

    def test_specification_fallback_uses_customer_facing_summary_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
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
                    "case_id": "CASE-TEST-010",
                    "workspace_path": str(workspace_path),
                    "workflow_kind": "ambiguous_case",
                    "intake_category": "specification_inquiry",
                    "knowledge_retrieval_final_adopted_source": "ai-chat-util",
                    "knowledge_retrieval_results": [
                        {
                            "source_name": "ai-chat-util",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "ai_chat_util は、生成AIを使ったチャット、文書解析、バッチ処理、MCP 連携をまとめて扱うためのユーティリティです。",
                            "matched_paths": ["/knowledge/ai-chat-util/README.md"],
                            "feature_bullets": [
                                "テキストチャットを LLM に送る",
                                "Excel 入力でバッチ処理を回す",
                                "画像、PDF、Office 文書を解析する",
                            ],
                        }
                    ],
                    "raw_issue": "ai-chat-utilの機能一覧を出して",
                    "investigation_summary": "SuperVisorAgent は共有メモリを参照し、KnowledgeRetrieverAgent を使って調査を進めます。",
                }
            )

            draft = str(result.get("draft_response") or "")
            self.assertIn("ai-chat-util について、現時点で確認できた内容は以下のとおりです。", draft)
            self.assertIn("主な機能:", draft)
            self.assertIn("- テキストチャットを LLM に送る", draft)
            self.assertIn("[ai-chat-util](/knowledge/ai-chat-util/README.md)", draft)
            self.assertNotIn("[ai-platform-poc]", draft)
            self.assertNotIn("SuperVisorAgent", draft)
            self.assertNotIn("KnowledgeRetrieverAgent", draft)

    def test_draft_writer_hides_internal_compliance_revision_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
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

    def test_specification_fallback_treats_detailed_request_with_feature_bullets_as_list_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
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
                    "case_id": "CASE-TEST-DETAIL-001",
                    "workspace_path": str(workspace_path),
                    "workflow_kind": "ambiguous_case",
                    "intake_category": "specification_inquiry",
                    "knowledge_retrieval_final_adopted_source": "ai-chat-util",
                    "knowledge_retrieval_results": [
                        {
                            "source_name": "ai-chat-util",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "ai_chat_util は生成AI関連ユーティリティです。",
                            "matched_paths": ["/knowledge/ai-chat-util/README.md"],
                            "feature_bullets": [
                                "テキストチャットを LLM に送る",
                                "Excel 入力でバッチ処理を回す",
                            ],
                        }
                    ],
                    "raw_issue": "ai-chat-utilについて詳細に教えて",
                    "investigation_summary": "関連資料を確認しました。",
                }
            )

            draft = str(result.get("draft_response") or "")
            self.assertIn("主な機能:", draft)
            self.assertIn("- テキストチャットを LLM に送る", draft)

    def test_specification_fallback_uses_raw_backend_payload_for_detailed_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
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
                    "case_id": "CASE-TEST-DETAIL-RAW-001",
                    "workspace_path": str(workspace_path),
                    "workflow_kind": "specification_inquiry",
                    "intake_category": "specification_inquiry",
                    "knowledge_retrieval_final_adopted_source": "ai-chat-util",
                    "knowledge_retrieval_results": [
                        {
                            "source_name": "ai-chat-util",
                            "source_type": "document_source",
                            "status": "matched",
                            "summary": "# ai-chat-util\n\n## できること\n- テキストチャットを LLM に送る",
                            "matched_paths": ["/knowledge/ai-chat-util/README.md"],
                            "feature_bullets": [],
                            "raw_backend": {
                                "mode": "raw_backend",
                                "file_data": {
                                    "content": "# ai-chat-util\n\n## できること\n\n- テキストチャットを LLM に送る\n- Excel 入力でバッチ処理を回す\n",
                                    "encoding": "utf-8",
                                },
                                "grep_matches": [],
                                "glob_matches": [],
                            },
                        }
                    ],
                    "raw_issue": "ai-chat-utilについて詳細に教えて",
                    "investigation_summary": "関連資料を確認しました。",
                }
            )

            draft = str(result.get("draft_response") or "")
            self.assertIn("主な機能:", draft)
            self.assertIn("- テキストチャットを LLM に送る", draft)


if __name__ == "__main__":
    unittest.main()