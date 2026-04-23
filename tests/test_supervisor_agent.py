from __future__ import annotations

import json
import tempfile
import unittest
from asyncio import run
from pathlib import Path

from support_ope_agents.agents.production.investigate_agent import InvestigateAgent, InvestigateAgentTools
from support_ope_agents.agents.production.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_read_shared_memory import build_default_read_shared_memory_tool
from support_ope_agents.tools.default_write_shared_memory import build_default_write_shared_memory_tool


class SupervisorPhaseExecutorHelpersTests(unittest.TestCase):
    def test_review_excerpt_truncation_is_disabled_by_default(self) -> None:
        text = "B" * 260

        self.assertEqual(SupervisorPhaseExecutor._summarize_text(text, limit=None), text)


class _FakeInvestigateExecutor:
    @staticmethod
    def execute(_state: dict[str, object]) -> dict[str, object]:
        return {
            "investigation_summary": "生成AI基盤の 3 層構成を説明しました。",
            "log_analysis_summary": "",
            "log_analysis_file": "",
            "knowledge_retrieval_summary": "2 つのソースから候補を取得しました。",
            "knowledge_retrieval_results": [
                {
                    "source_name": "internal_ticket",
                    "source_type": "ticket_source",
                    "status": "hydrated",
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
            "knowledge_retrieval_final_adopted_source": "ai-platform-poc",
        }


class _FakeExplicitSourceInvestigateExecutor:
    @staticmethod
    def execute(_state: dict[str, object]) -> dict[str, object]:
        return {
            "investigation_summary": "チャットユーティリティの機能一覧を説明しました。",
            "log_analysis_summary": "",
            "log_analysis_file": "",
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
            "knowledge_retrieval_final_adopted_source": "ai-chat-util",
        }


class SupervisorAgentTests(unittest.TestCase):
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

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                escalation_settings=config.agents.BackSupportEscalationAgent.escalation,
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-ESC-001",
                    "workspace_path": tmpdir,
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

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                investigate_executor=_FakeInvestigateExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-005",
                    "workspace_path": tmpdir,
                    "execution_mode": "action",
                    "workflow_kind": "specification_inquiry",
                    "intake_category": "specification_inquiry",
                    "intake_urgency": "medium",
                    "raw_issue": "生成AI基盤のアーキテクチャ概要を確認したい",
                }
            )

            self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-platform-poc")
            self.assertEqual(result.get("knowledge_retrieval_adopted_sources") or [], ["ai-platform-poc"])

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

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                investigate_executor=_FakeExplicitSourceInvestigateExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-QUERY-001",
                    "workspace_path": tmpdir,
                    "execution_mode": "action",
                    "workflow_kind": "specification_inquiry",
                    "intake_category": "specification_inquiry",
                    "intake_urgency": "medium",
                    "raw_issue": "ai-chat-utilの機能一覧を出して",
                }
            )

            self.assertEqual(str(result.get("knowledge_retrieval_final_adopted_source") or ""), "ai-chat-util")

    def test_consolidated_investigate_log_summary_includes_exception_details(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        executor = InvestigateAgent(
            config=config,
            tools=InvestigateAgentTools(
                detect_log_format_tool=lambda *_args, **_kwargs: json.dumps(
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
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            evidence_dir = workspace_path / ".evidence"
            evidence_dir.mkdir()
            (evidence_dir / "vdp.log").write_text("sample", encoding="utf-8")

            result = executor.execute({"workspace_path": str(workspace_path), "raw_issue": "vdp.log のエラーを見て"})

        summary = str(result.get("log_analysis_summary") or "")
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

            supervisor = SupervisorPhaseExecutor(
                read_shared_memory_tool=read_shared_memory,
                write_shared_memory_tool=write_shared_memory,
                investigate_executor=_FakeInvestigateExecutor(),
            )

            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-CUSTOMER-001",
                    "workspace_path": tmpdir,
                    "execution_mode": "action",
                    "workflow_kind": "incident_investigation",
                    "intake_category": "incident_investigation",
                    "intake_urgency": "medium",
                    "intake_incident_timeframe": "2026-04-10 10:15 頃",
                    "raw_issue": "Denodo の vdp.log のエラー調査をお願いします",
                }
            )

            investigation_summary = str(result.get("investigation_summary") or "")
            self.assertNotIn("SuperVisorAgent", investigation_summary)
            self.assertNotIn("KnowledgeRetrieverAgent", investigation_summary)

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
                investigate_executor=_FakeInvestigateExecutor(),
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
            self.assertIn("Primary source:", summary)


if __name__ == "__main__":
    unittest.main()
