from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool


class DraftWriterTests(unittest.TestCase):
    def test_draft_writer_uses_compliance_notice_settings(self) -> None:
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

            self.assertIn(
                "この回答は生成AI補助を含み、誤りの可能性があります",
                str(result.get("draft_response") or ""),
            )
            draft = str(result.get("draft_response") or "")
            self.assertTrue(draft.endswith("【注意事項】この回答は生成AI補助を含み、誤りの可能性があります。"))
            self.assertLess(
                draft.find("お問い合わせありがとうございます。"),
                draft.find("【注意事項】この回答は生成AI補助を含み、誤りの可能性があります。"),
            )

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


if __name__ == "__main__":
    unittest.main()