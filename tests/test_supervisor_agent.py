from __future__ import annotations

import json
import tempfile
import unittest
from asyncio import run
from pathlib import Path

from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor
from support_ope_agents.agents.production.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_read_shared_memory import build_default_read_shared_memory_tool
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool
from support_ope_agents.tools.default_write_shared_memory import build_default_write_shared_memory_tool


class SupervisorPhaseExecutorHelpersTests(unittest.TestCase):
    def test_review_excerpt_truncation_is_disabled_by_default(self) -> None:
        text = "B" * 260

        self.assertEqual(SupervisorPhaseExecutor._summarize_text(text, limit=None), text)


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


class _FakeSequentialDraftWriterExecutor:
    def __init__(self, drafts: list[str]) -> None:
        self._drafts = drafts
        self.calls = 0

    def execute(self, _state: dict[str, object]) -> dict[str, object]:
        index = min(self.calls, len(self._drafts) - 1)
        self.calls += 1
        return {"draft_response": self._drafts[index]}


class _FakeFollowupLogAnalyzerExecutor:
    def __init__(self) -> None:
        self.raw_issues: list[str] = []

    def execute(self, state: dict[str, object]) -> dict[str, object]:
        raw_issue = str(state.get("raw_issue") or "")
        self.raw_issues.append(raw_issue)
        if len(self.raw_issues) == 1:
            return {
                "summary": (
                    "vdp.log を解析し、形式は unknown と判定しました。severity 一致 1 件、例外一致 1 件。"
                    "検出した例外候補: com.denodo.vdb.cache.VDBCacheException。"
                    "代表的な例外行: L9: com.denodo.vdb.cache.VDBCacheException: Data source vdpcachedatasource not found。"
                ),
                "file": "/tmp/vdp.log",
            }
        return {
            "summary": "追加調査として Data source vdpcachedatasource の参照失敗が再現条件と一致することを確認しました。",
            "file": "/tmp/vdp.log",
        }


class _FakeFollowupKnowledgeRetrieverExecutor:
    def __init__(self) -> None:
        self.raw_issues: list[str] = []

    def execute(self, state: dict[str, object]) -> dict[str, object]:
        raw_issue = str(state.get("raw_issue") or "")
        self.raw_issues.append(raw_issue)
        if "vdpcachedatasource" in raw_issue:
            return {
                "knowledge_retrieval_summary": "Denodo の既知事例から Data source 名不一致時は定義名と接続設定の再確認が必要と分かりました。",
                "knowledge_retrieval_results": [
                    {
                        "source_name": "denodo-troubleshooting",
                        "source_type": "document_source",
                        "status": "matched",
                        "summary": "Data source 名の不一致時は定義と接続設定を確認する",
                        "matched_paths": ["/knowledge/denodo/troubleshooting.md"],
                        "evidence": ["Data source 名と定義ファイルの一致確認"],
                    }
                ],
                "knowledge_retrieval_adopted_sources": ["denodo-troubleshooting"],
            }
        return {
            "knowledge_retrieval_summary": "Denodo 関連の一般調査資料を確認しました。",
            "knowledge_retrieval_results": [
                {
                    "source_name": "denodo-overview",
                    "source_type": "document_source",
                    "status": "matched",
                    "summary": "Denodo ログ調査の概要",
                    "matched_paths": ["/knowledge/denodo/overview.md"],
                    "evidence": ["Data source の定義を確認"],
                }
            ],
            "knowledge_retrieval_adopted_sources": ["denodo-overview"],
        }


class SupervisorAgentTests(unittest.TestCase):
    pass

    def test_supervisor_instruction_only_and_bypass_disable_runtime_constraints(self) -> None:
        for constraint_mode in ("instruction_only", "bypass"):
            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=lambda *_args: json.dumps({"context": "", "progress": "", "summary": ""}, ensure_ascii=False),
                write_shared_memory_tool=lambda *_args: "",
                constraint_mode=constraint_mode,
            )

            self.assertFalse(supervisor._runtime_constraints_enabled())

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

    def test_supervisor_runs_followup_investigation_when_new_fact_found(self) -> None:
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
            log_executor = _FakeFollowupLogAnalyzerExecutor()
            knowledge_executor = _FakeFollowupKnowledgeRetrieverExecutor()

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                log_analyzer_executor=log_executor,
                knowledge_retriever_executor=knowledge_executor,
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-FOLLOWUP-001",
                    "workspace_path": tmpdir,
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "high",
                    "raw_issue": "vdp.log のエラーを確認したい",
                }
            )

            self.assertEqual(len(log_executor.raw_issues), 2)
            self.assertEqual(len(knowledge_executor.raw_issues), 2)
            self.assertIn("vdpcachedatasource", knowledge_executor.raw_issues[1])
            self.assertEqual(int(result.get("investigation_followup_loops") or 0), 1)
            self.assertTrue(list(result.get("supervisor_followup_notes") or []))
            self.assertIn("追加調査", str(result.get("knowledge_retrieval_summary") or ""))

    def test_supervisor_writes_summary_with_rationale_and_next_action(self) -> None:
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

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                log_analyzer_executor=_FakeLogAnalyzerExecutor(),
                knowledge_retriever_executor=_FakeKnowledgeRetrieverExecutor(),
            )

            supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-SUMMARY-001",
                    "workspace_path": tmpdir,
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "medium",
                    "raw_issue": "vdp.log のエラー調査",
                }
            )

            memory_result = json.loads(run(read_shared_memory("CASE-TEST-SUMMARY-001", tmpdir)))
            summary = str(memory_result.get("summary") or "")
            self.assertIn("Conclusion:", summary)
            self.assertIn("Judgment rationale:", summary)
            self.assertIn("Next action:", summary)
            self.assertIn("java.net.SocketTimeoutException", summary)
            self.assertIn("L12:", summary)
            self.assertIn("調査結果を回答ドラフトへ反映します。", summary)
            self.assertIn("Primary source: log analysis", summary)

if __name__ == "__main__":
    unittest.main()
