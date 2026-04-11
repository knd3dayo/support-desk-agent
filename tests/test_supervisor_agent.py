from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.agents.compliance_reviewer_agent import ComplianceReviewerPhaseExecutor
from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_read_shared_memory import build_default_read_shared_memory_tool
from support_ope_agents.tools.default_check_policy import build_default_check_policy_tool
from support_ope_agents.tools.default_request_revision import build_default_request_revision_tool
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool
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


class _FakeExplicitSourceKnowledgeRetrieverExecutor:
    @staticmethod
    def execute(_state: dict[str, object]) -> dict[str, object]:
        return {
            "knowledge_retrieval_summary": "2 つのソースから候補を取得しました。",
            "knowledge_retrieval_results": [
                {
                    "source_name": "ai-platform-poc",
                    "source_type": "document_source",
                    "status": "matched",
                    "summary": "生成AI基盤の 3 層構成を説明",
                    "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                    "evidence": ["Application層", "Tool層", "AIガバナンス層"],
                },
                {
                    "source_name": "ai-chat-util",
                    "source_type": "document_source",
                    "status": "matched",
                    "summary": "チャットユーティリティの機能一覧を説明",
                    "matched_paths": ["/knowledge/ai-chat-util/README.md"],
                    "evidence": ["機能一覧"],
                },
            ],
            "knowledge_retrieval_adopted_sources": ["ai-platform-poc", "ai-chat-util"],
        }


class _FakeMissingLogsAnalyzerExecutor:
    @staticmethod
    def execute(_state: dict[str, object]) -> dict[str, object]:
        return {
            "summary": "ログファイルが見つからなかったため、既知事例との照合を優先します。",
            "file": "",
        }


class _FakeDraftModel:
    async def ainvoke(self, _messages):
        return AIMessage(content="生成AIは誤った回答をすることがあります。現時点では仕様上の動作と判断します。")


class _FakeComplianceModel:
    async def ainvoke(self, _messages):
        return AIMessage(content='{"summary":"mocked compliance review","issues":[]}')


class _FakeLogAnalyzerExecutor:
    @staticmethod
    def execute(_state: dict[str, object]) -> dict[str, object]:
        return {
            "summary": (
                "vdp.log を解析し、形式は unknown と判定しました。severity 一致 2 件、例外一致 1 件。"
                "主な severity: ERROR。検出した例外候補: java.net.SocketTimeoutException。"
                "代表的な異常行: L12: ERROR Request timeout while querying VDP."
            ),
            "file": "/tmp/vdp.log",
        }


class _FakePolicyUnavailableComplianceExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, _state: dict[str, object]) -> dict[str, object]:
        self.calls += 1
        return {
            "compliance_review_summary": "ドラフトはポリシー照合で修正が必要です。",
            "compliance_review_results": [],
            "compliance_review_adopted_sources": [],
            "compliance_review_issues": [
                "確認根拠となるポリシー文書を取得できませんでした。document_sources の設定と配置を確認してください。"
            ],
            "compliance_notice_present": False,
            "compliance_notice_matched_phrase": "",
            "compliance_revision_request": "確認根拠となるポリシー文書を取得できませんでした。document_sources の設定と配置を確認してください。",
            "compliance_review_passed": False,
        }


class _FakeSequentialDraftWriterExecutor:
    def __init__(self, drafts: list[str]) -> None:
        self._drafts = drafts
        self.calls = 0

    def execute(self, _state: dict[str, object]) -> dict[str, object]:
        index = min(self.calls, len(self._drafts) - 1)
        self.calls += 1
        return {"draft_response": self._drafts[index]}


class _FakeSequentialComplianceExecutor:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = responses
        self.calls = 0

    def execute(self, _state: dict[str, object]) -> dict[str, object]:
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return dict(self._responses[index])


class SupervisorAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._compliance_model_patcher = patch(
            "support_ope_agents.tools.default_check_policy._get_chat_model",
            return_value=_FakeComplianceModel(),
        )
        self._compliance_model_patcher.start()

    def tearDown(self) -> None:
        self._compliance_model_patcher.stop()

    def test_supervisor_uses_back_support_escalation_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "BackSupportEscalationAgent": {
                            "escalation": {
                                "uncertainty_markers": ["need_escalation_marker"],
                                "missing_log_markers": ["custom missing logs"],
                                "default_missing_artifacts_by_workflow": {
                                    "incident_investigation": ["カスタムログ一式"],
                                    "specification_inquiry": ["仕様差分の根拠資料"],
                                    "ambiguous_case": ["追加ヒアリング結果"],
                                },
                            }
                        }
                    },
                }
            )
            read_shared_memory = build_default_read_shared_memory_tool(config)
            write_shared_memory = build_default_write_shared_memory_tool(config)
            workspace_path = Path(tmpdir)

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                escalation_settings=config.agents.BackSupportEscalationAgent.escalation,
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-ESC-001",
                    "workspace_path": str(workspace_path),
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "high",
                    "intake_incident_timeframe": "2026-04-10 10:15 頃",
                    "raw_issue": "障害調査",
                    "investigation_summary": "need_escalation_marker が残っています",
                    "log_analysis_summary": "custom missing logs",
                }
            )

            self.assertTrue(bool(result.get("escalation_required")))
            self.assertIn("カスタムログ一式", list(result.get("escalation_missing_artifacts") or []))
    def test_supervisor_records_final_adopted_knowledge_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
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

    def test_supervisor_does_not_escalate_on_missing_logs_when_knowledge_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
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
                log_analyzer_executor=_FakeMissingLogsAnalyzerExecutor(),
                knowledge_retriever_executor=_FakeKnowledgeRetrieverExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-LOG-001",
                    "workspace_path": str(workspace_path),
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "medium",
                    "intake_incident_timeframe": "2026-04-10 10:15 頃",
                    "raw_issue": "接続断が発生したが既知事例の回避策があるか確認したい",
                }
            )

            self.assertFalse(bool(result.get("escalation_required")))
            self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-platform-poc")

    def test_supervisor_prefers_explicitly_named_knowledge_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
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
                knowledge_retriever_executor=_FakeExplicitSourceKnowledgeRetrieverExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-QUERY-001",
                    "workspace_path": str(workspace_path),
                    "execution_mode": "action",
                    "workflow_kind": "specification_inquiry",
                    "intake_category": "specification_inquiry",
                    "intake_urgency": "medium",
                    "raw_issue": "ai-chat-utilの機能一覧を出して",
                }
            )

            self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-chat-util")

    def test_log_analyzer_summary_includes_exception_details(self) -> None:
        executor = LogAnalyzerPhaseExecutor(
            detect_log_format_tool=lambda *_args: json.dumps(
                {
                    "detected_format": "unknown",
                    "has_java_stacktrace": True,
                    "search_results": {
                        "severity": [
                            {"line_number": 12, "line": "2026-04-10 10:15:00 ERROR Request timeout while querying VDP"},
                            {"line_number": 13, "line": "2026-04-10 10:15:01 WARN retry scheduled"},
                        ],
                        "java_exception": [
                            {"line_number": 14, "line": "java.net.SocketTimeoutException: Read timed out"}
                        ],
                    },
                },
                ensure_ascii=False,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            evidence_dir = workspace_path / ".evidence"
            evidence_dir.mkdir()
            (evidence_dir / "vdp.log").write_text("sample", encoding="utf-8")

            result = executor.execute({"workspace_path": str(workspace_path), "raw_issue": "vdp.log のエラーを見て"})

        summary = str(result.get("summary") or "")
        self.assertIn("主な severity: ERROR, WARN", summary)
        self.assertIn("java.net.SocketTimeoutException", summary)
        self.assertIn("代表的な異常行: L12:", summary)

    def test_supervisor_builds_customer_facing_investigation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
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
                log_analyzer_executor=_FakeLogAnalyzerExecutor(),
                knowledge_retriever_executor=_FakeKnowledgeRetrieverExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-CUSTOMER-001",
                    "workspace_path": str(workspace_path),
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "medium",
                    "intake_incident_timeframe": "2026-04-10 10:15 頃",
                    "raw_issue": "Denodo の vdp.log のエラー調査をお願いします",
                }
            )

            investigation_summary = str(result.get("investigation_summary") or "")
            self.assertIn("vdp.log を解析", investigation_summary)
            self.assertNotIn("SuperVisorAgent", investigation_summary)
            self.assertNotIn("KnowledgeRetrieverAgent", investigation_summary)
            self.assertNotIn("ナレッジ照会結果", investigation_summary)

    def test_supervisor_stops_on_policy_unavailable_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {},
                }
            )
            read_shared_memory = build_default_read_shared_memory_tool(config)
            write_shared_memory = build_default_write_shared_memory_tool(config)
            compliance_executor = _FakePolicyUnavailableComplianceExecutor()

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                draft_writer_executor=DraftWriterPhaseExecutor(
                    config=config,
                    write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
                ),
                compliance_reviewer_executor=compliance_executor,
                compliance_max_review_loops=3,
            )

            result = supervisor.execute_draft_review(
                {
                    "case_id": "CASE-TEST-POLICY-001",
                    "workspace_path": str(Path(tmpdir)),
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "medium",
                    "investigation_summary": "vdp.log を確認し、タイムアウト系の異常を整理しました。",
                    "draft_response": "お問い合わせありがとうございます。vdp.log を確認したところ、タイムアウトに関するエラーを確認しました。",
                }
            )

            self.assertTrue(bool(result.get("compliance_review_passed")))
            self.assertEqual(int(result.get("draft_review_iterations") or 0), 1)
            self.assertEqual(compliance_executor.calls, 1)
            self.assertEqual(result.get("next_action"), "ApprovalAgent へドラフトを回付する")

    def test_supervisor_records_compliance_review_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {},
                }
            )
            read_shared_memory = build_default_read_shared_memory_tool(config)
            write_shared_memory = build_default_write_shared_memory_tool(config)
            draft_executor = _FakeSequentialDraftWriterExecutor(
                [
                    "初回ドラフトです。復旧を約束します。",
                    "修正版ドラフトです。現時点で確認できた範囲をご案内します。",
                ]
            )
            compliance_executor = _FakeSequentialComplianceExecutor(
                [
                    {
                        "compliance_review_summary": "断定表現の修正が必要です。",
                        "compliance_review_results": [],
                        "compliance_review_adopted_sources": ["answer_policy"],
                        "compliance_review_issues": ["復旧を断定しているため表現を弱めてください。"],
                        "compliance_notice_present": True,
                        "compliance_notice_matched_phrase": "生成AIは誤った回答をすることがあります。",
                        "compliance_revision_request": "復旧を断定せず、現時点で確認できた範囲に表現を修正してください。",
                        "compliance_review_passed": False,
                    },
                    {
                        "compliance_review_summary": "修正内容を確認し、レビューを通過しました。",
                        "compliance_review_results": [],
                        "compliance_review_adopted_sources": ["answer_policy"],
                        "compliance_review_issues": [],
                        "compliance_notice_present": True,
                        "compliance_notice_matched_phrase": "生成AIは誤った回答をすることがあります。",
                        "compliance_revision_request": "",
                        "compliance_review_passed": True,
                    },
                ]
            )

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                draft_writer_executor=draft_executor,
                compliance_reviewer_executor=compliance_executor,
                compliance_max_review_loops=3,
            )

            result = supervisor.execute_draft_review(
                {
                    "case_id": "CASE-TEST-HISTORY-001",
                    "workspace_path": str(Path(tmpdir)),
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "medium",
                    "investigation_summary": "vdp.log からタイムアウト系エラーを確認しました。",
                }
            )

            history = result.get("compliance_review_history") or []
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["iteration"], 1)
            self.assertEqual(history[0]["addressed_revision_request"], "")
            self.assertIn("復旧を断定せず", str(history[0]["compliance_revision_request"]))
            self.assertEqual(history[1]["iteration"], 2)
            self.assertIn("復旧を断定せず", str(history[1]["addressed_revision_request"]))
            self.assertTrue(bool(history[1]["passed"]))
            self.assertIn("修正版ドラフト", str(history[1]["draft_response"]))

    def test_supervisor_draft_review_records_compliance_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            policy_root = workspace_path / "policy"
            policy_root.mkdir()
            (policy_root / "guideline.md").write_text(
                "# 回答ポリシー\n\n生成AIを利用した回答には注意文を含め、断定表現を避ける。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "notice": {"required": True},
                            "document_sources": [
                                {
                                    "name": "answer_policy",
                                    "description": "回答ポリシー",
                                    "path": str(policy_root),
                                }
                            ]
                        }
                    },
                }
            )
            read_shared_memory = build_default_read_shared_memory_tool(config)
            write_shared_memory = build_default_write_shared_memory_tool(config)
            compliance_executor = ComplianceReviewerPhaseExecutor(
                check_policy_tool=build_default_check_policy_tool(config),
                request_revision_tool=build_default_request_revision_tool(),
            )
            draft_writer_executor = DraftWriterPhaseExecutor(
                config=config,
                write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
            )

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                draft_writer_executor=draft_writer_executor,
                compliance_reviewer_executor=compliance_executor,
            )

            result = supervisor.execute_draft_review(
                {
                    "case_id": "CASE-TEST-006",
                    "workspace_path": str(workspace_path),
                    "execution_mode": "action",
                    "workflow_kind": "specification_inquiry",
                    "intake_category": "specification_inquiry",
                    "intake_urgency": "medium",
                    "draft_response": "生成AIは誤った回答をすることがあります。現時点では仕様上の動作と判断します。",
                }
            )

            self.assertTrue(bool(result.get("compliance_review_passed")))
            self.assertTrue(bool(result.get("compliance_notice_present")))
            self.assertEqual(result.get("next_action"), "ApprovalAgent へドラフトを回付する")
            self.assertEqual(result.get("compliance_review_adopted_sources") or [], ["answer_policy"])
            self.assertEqual(result.get("draft_review_iterations"), 1)

    def test_supervisor_retries_draft_until_compliance_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            policy_root = workspace_path / "policy"
            policy_root.mkdir()
            (policy_root / "guideline.md").write_text(
                "# 回答ポリシー\n\n生成AIを利用した回答には注意文を含め、断定表現を避ける。",
                encoding="utf-8",
            )
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {
                        "ComplianceReviewerAgent": {
                            "max_review_loops": 3,
                            "notice": {"required": True},
                            "document_sources": [
                                {
                                    "name": "answer_policy",
                                    "description": "回答ポリシー",
                                    "path": str(policy_root),
                                }
                            ]
                        }
                    },
                }
            )
            read_shared_memory = build_default_read_shared_memory_tool(config)
            write_shared_memory = build_default_write_shared_memory_tool(config)
            compliance_executor = ComplianceReviewerPhaseExecutor(
                check_policy_tool=build_default_check_policy_tool(config),
                request_revision_tool=build_default_request_revision_tool(),
            )
            draft_writer_executor = DraftWriterPhaseExecutor(
                config=config,
                write_draft_tool=build_default_write_draft_tool(config, "customer_response_draft"),
            )

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                draft_writer_executor=draft_writer_executor,
                compliance_reviewer_executor=compliance_executor,
                compliance_max_review_loops=3,
            )

            with patch("support_ope_agents.agents.draft_writer_agent._get_chat_model", return_value=_FakeDraftModel()):
                result = supervisor.execute_draft_review(
                    {
                        "case_id": "CASE-TEST-007",
                        "workspace_path": str(workspace_path),
                        "execution_mode": "action",
                        "workflow_kind": "incident_investigation",
                        "intake_category": "incident_investigation",
                        "intake_urgency": "high",
                        "investigation_summary": "現時点では再現条件を確認中であり、仕様逸脱は断定していません。",
                        "draft_response": "必ず復旧します。",
                    }
                )

            self.assertTrue(bool(result.get("compliance_review_passed")))
            self.assertGreaterEqual(int(result.get("draft_review_iterations") or 0), 1)
            self.assertEqual(result.get("draft_review_max_loops"), 3)
            self.assertIn("生成AIは誤った回答をすることがあります", str(result.get("draft_response") or ""))


if __name__ == "__main__":
    unittest.main()
