from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.agents.compliance_reviewer_agent import ComplianceReviewerPhaseExecutor
from support_ope_agents.config import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_check_policy import build_default_check_policy_tool
from support_ope_agents.tools.default_request_revision import build_default_request_revision_tool
from support_ope_agents.tools.registry import ToolRegistry


class ComplianceReviewerTests(unittest.TestCase):
    def test_check_policy_finds_policy_sources_and_missing_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_root = Path(tmpdir) / "policy"
            policy_root.mkdir()
            (policy_root / "guideline.md").write_text(
                "# 回答ガイドライン\n\n生成AIを利用した回答には注意書きを含める。断定的な表現は避ける。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "notice": {"required": True},
                            "document_sources": [
                                {
                                    "name": "internal_policy",
                                    "description": "社内回答ガイドライン",
                                    "path": str(policy_root),
                                }
                            ]
                        }
                    },
                }
            )

            tool = build_default_check_policy_tool(config)
            raw = asyncio.run(tool(draft_response="この回答は必ず正しいです。", review_focus="注意文と断定表現を確認する"))
            result = json.loads(raw)

            self.assertEqual(result["status"], "revision_required")
            self.assertEqual(result["adopted_sources"], ["internal_policy"])
            self.assertFalse(result["notice_check"]["present"])
            self.assertTrue(any("注意文が不足" in issue for issue in result["issues"]))
            self.assertTrue(any("断定的な表現" in issue for issue in result["issues"]))

    def test_loader_resolves_compliance_document_source_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy_root = root / "policy-docs"
            policy_root.mkdir()
            config_path = root / "config.yml"
            config_path.write_text(
                """
support_ope_agents:
  llm:
    provider: openai
    model: gpt-4.1
    api_key: dummy
  config_paths: {}
  data_paths: {}
  interfaces: {}
  agents:
    ComplianceReviewerAgent:
      document_sources:
        - name: government_guideline
          description: 行政ガイドライン
          path: ./policy-docs
      ignore_patterns_file: ./.policy-ignore
""".strip(),
                encoding="utf-8",
            )
            (root / ".policy-ignore").write_text("*.tmp\n", encoding="utf-8")

            config = load_config(config_path)

            self.assertEqual(
                config.agents.ComplianceReviewerAgent.document_sources[0].path,
                policy_root.resolve(),
            )
            self.assertEqual(
                config.agents.ComplianceReviewerAgent.ignore_patterns_file,
                (root / ".policy-ignore").resolve(),
            )

    def test_executor_generates_revision_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_root = Path(tmpdir) / "policy"
            policy_root.mkdir()
            (policy_root / "law.md").write_text(
                "# 法令抜粋\n\n生成AIを利用した回答には誤りの可能性を注意喚起する。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "notice": {"required": True},
                            "document_sources": [
                                {
                                    "name": "law",
                                    "description": "法令集",
                                    "path": str(policy_root),
                                }
                            ]
                        }
                    },
                }
            )
            executor = ComplianceReviewerPhaseExecutor(
                check_policy_tool=build_default_check_policy_tool(config),
                request_revision_tool=build_default_request_revision_tool(),
            )

            result = executor.execute(
                {
                    "draft_response": "本回答で問題ありません。",
                    "review_focus": "法令根拠と注意文を確認する",
                }
            )

            self.assertFalse(result["compliance_review_passed"])
            self.assertFalse(result["compliance_notice_present"])
            self.assertIn("注意文", result["compliance_revision_request"])

    def test_writes_raw_policy_results_to_working_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            policy_root = workspace_path / "policy"
            policy_root.mkdir()
            (policy_root / "guideline.md").write_text(
                "# 回答ガイドライン\n\n生成AIを利用した回答には注意書きを含める。断定的な表現は避ける。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "notice": {"required": True},
                            "document_sources": [
                                {
                                    "name": "internal_policy",
                                    "description": "社内回答ガイドライン",
                                    "path": str(policy_root),
                                }
                            ],
                        }
                    },
                }
            )
            executor = ComplianceReviewerPhaseExecutor(
                check_policy_tool=build_default_check_policy_tool(config),
                request_revision_tool=build_default_request_revision_tool(),
                write_working_memory_tool=ToolRegistry(config).get_tools("ComplianceReviewerAgent")[-1].handler,
            )

            executor.execute(
                {
                    "case_id": "CASE-TEST-COMP-WM-001",
                    "workspace_path": str(workspace_path),
                    "draft_response": "この回答は必ず正しいです。",
                    "review_focus": "注意文と断定表現を確認する",
                }
            )

            working_path = workspace_path / ".memory" / "agents" / "ComplianceReviewerAgent" / "working.md"
            content = working_path.read_text(encoding="utf-8")
            self.assertIn("## Result: internal_policy", content)
            self.assertIn("Raw result:", content)
            self.assertIn('"source_name": "internal_policy"', content)

    def test_max_review_loops_defaults_to_three(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        self.assertEqual(config.agents.ComplianceReviewerAgent.max_review_loops, 3)

    def test_notice_is_optional_by_default(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        self.assertFalse(config.agents.ComplianceReviewerAgent.notice.required)

    def test_check_policy_raw_backend_mode_includes_backend_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_root = Path(tmpdir) / "policy"
            policy_root.mkdir()
            (policy_root / "guideline.md").write_text(
                "# 回答ガイドライン\n\n生成AIを利用した回答には注意書きを含める。断定的な表現は避ける。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "document_sources": [
                                {
                                    "name": "internal_policy",
                                    "description": "社内回答ガイドライン",
                                    "path": str(policy_root),
                                }
                            ],
                            "extraction_mode": "raw_backend",
                        }
                    },
                }
            )

            tool = build_default_check_policy_tool(config)
            raw = asyncio.run(tool(draft_response="この回答は必ず正しいです。", review_focus="注意文と断定表現を確認する"))
            result = json.loads(raw)

            self.assertIn("raw_backend", result["results"][0])
            self.assertEqual(result["results"][0]["raw_backend"]["mode"], "raw_backend")

    def test_check_policy_can_expand_keywords_with_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_root = Path(tmpdir) / "policy"
            policy_root.mkdir()
            (policy_root / "guideline.md").write_text(
                "# 回答ガイドライン\n\n独自注記を含む回答は禁止です。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "document_sources": [
                                {
                                    "name": "internal_policy",
                                    "description": "社内回答ガイドライン",
                                    "path": str(policy_root),
                                }
                            ],
                            "policy_keywords": [],
                            "policy_keyword_expansion_enabled": True,
                            "policy_keyword_expansion_count": 3,
                        }
                    },
                }
            )

            class _FakeResponse:
                def __init__(self, content: str):
                    self.content = content

            class _FakeModel:
                async def ainvoke(self, messages):
                    prompt = str(messages[0].content)
                    if "Expand the review query" in prompt:
                        return _FakeResponse('{"keywords": ["独自注記"]}')
                    return _FakeResponse('{"summary": "reviewed", "issues": []}')

            with patch("support_ope_agents.tools.default_check_policy._get_chat_model", return_value=_FakeModel()):
                tool = build_default_check_policy_tool(config)
                raw = asyncio.run(tool(draft_response="この回答は必ず正しいです。", review_focus="注意文と断定表現を確認する"))

            result = json.loads(raw)
            self.assertIn("独自注記を含む回答は禁止です。", result["results"][0]["evidence"][0])


if __name__ == "__main__":
    unittest.main()