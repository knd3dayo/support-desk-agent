from __future__ import annotations

from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.reporting import MemoryConsistencyFinding, _build_objective_evaluation, _build_sequence_diagram, _build_subgraph_sequence_diagrams, _extract_instruction_criteria, _render_ticket_fetch_error_section, _render_ticket_info_section, _ticket_lookup_detail, _ticket_lookup_status
from support_ope_agents.models.state import CaseState


class ReportingEvaluationTests(unittest.TestCase):
    def test_app_config_rejects_placeholder_llm_api_key(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {},
                }
            )

    def test_sequence_diagram_uses_customer_input_route(self) -> None:
        state: CaseState = {
            "workflow_kind": "ambiguous_case",
            "status": "WAITING_CUSTOMER_INPUT",
            "intake_category": "ambiguous_case",
        }

        diagram = _build_sequence_diagram(state)

        self.assertIn("Intake-->>User: 追加情報を依頼", diagram)
        self.assertNotIn("Supervisor->>Knowledge", diagram)

    def test_ticket_lookup_status_reports_success_when_ticket_artifact_exists(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        status = _ticket_lookup_status(
            {
                "internal_ticket_id": "2",
                "intake_ticket_artifacts": {"internal_ticket": ["/tmp/internal_ticket.json"]},
                "intake_ticket_context_summary": {},
                "agent_errors": [],
            },
            config=config,
            ticket_kind="internal",
        )

        self.assertEqual(status, "成功")

    def test_ticket_lookup_detail_reports_summary_and_artifact_on_success(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        detail = _ticket_lookup_detail(
            {
                "intake_ticket_context_summary": {"internal_ticket": "Issue 2: internal ticket summary"},
                "intake_ticket_artifacts": {"internal_ticket": ["/tmp/internal_ticket.json"]},
                "agent_errors": [],
            },
            config=config,
            ticket_kind="internal",
        )

        self.assertIn("summary: Issue 2: internal ticket summary", detail)
        self.assertIn("artifacts: /tmp/internal_ticket.json", detail)

    def test_ticket_lookup_status_reports_failure_from_agent_error(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        status = _ticket_lookup_status(
            {
                "internal_ticket_id": "2",
                "intake_ticket_context_summary": {},
                "intake_ticket_artifacts": {},
                "agent_errors": [
                    {
                        "agent": "IntakeAgent",
                        "phase": "internal_ticket_lookup",
                        "message": "Issue not found: 404",
                    }
                ],
            },
            config=config,
            ticket_kind="internal",
        )

        self.assertEqual(status, "失敗: Issue not found: 404")

    def test_ticket_lookup_detail_reports_error_on_failure(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        detail = _ticket_lookup_detail(
            {
                "intake_ticket_context_summary": {},
                "intake_ticket_artifacts": {},
                "agent_errors": [
                    {
                        "agent": "IntakeAgent",
                        "phase": "internal_ticket_lookup",
                        "message": "Issue not found: 404",
                    }
                ],
            },
            config=config,
            ticket_kind="internal",
        )

        self.assertEqual(detail, "Issue not found: 404")

    def test_render_ticket_fetch_error_section_outputs_raw_error_verbatim(self) -> None:
        lines = _render_ticket_fetch_error_section(
            {
                "agent_errors": [
                    {
                        "agent": "IntakeAgent",
                        "phase": "internal_ticket_lookup",
                        "message": "Traceback:\n  line 1\nHTTP 404: issue not found\n",
                    }
                ]
            }
        )

        self.assertEqual(
            lines,
            [
                "## チケット取得エラー詳細",
                "チケット取得に失敗した場合の生エラーメッセージです。整形や要約をせず、そのまま出力します。",
                "### Internal ticket raw error",
                "```text",
                "Traceback:\n  line 1\nHTTP 404: issue not found",
                "```",
            ],
        )

    def test_render_ticket_info_section_reports_both_ticket_kinds(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        lines = _render_ticket_info_section(
            {
                "external_ticket_id": "EXT-123",
                "internal_ticket_id": "INT-456",
                "external_ticket_lookup_enabled": True,
                "internal_ticket_lookup_enabled": True,
                "intake_ticket_context_summary": {
                    "external_ticket": "External summary",
                    "internal_ticket": "Internal summary",
                },
                "intake_ticket_artifacts": {
                    "external_ticket": ["/tmp/external.json"],
                    "internal_ticket": ["/tmp/internal.json"],
                },
                "agent_errors": [],
            },
            config=config,
        )

        self.assertIn("- External ticket ID: EXT-123", lines)
        self.assertIn("- External ticket fetch: 成功", lines)
        self.assertIn("- Internal ticket ID: INT-456", lines)
        self.assertIn("- Internal ticket fetch: 成功", lines)

    def test_ticket_lookup_detail_reports_skip_reason_when_manifest_missing(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "tools": {
                    "ticket_sources": {
                        "internal": {
                            "enabled": True,
                            "server": "github",
                            "arguments": {"owner": "knd3dayo", "repo": "support-ope-agents"},
                        }
                    }
                },
                "runtime": {"mode": "sample"},
                "agents": {},
            }
        )

        detail = _ticket_lookup_detail(
            {
                "internal_ticket_id": "2",
                "internal_ticket_lookup_enabled": True,
                "intake_ticket_context_summary": {},
                "intake_ticket_artifacts": {},
                "agent_errors": [],
            },
            config=config,
            ticket_kind="internal",
        )

        self.assertEqual(detail, "enabled: true だがfetch不可: MCP manifest 未設定")

    def test_ticket_lookup_status_reports_manifest_missing_for_sample_ticket_lookup(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "tools": {
                    "ticket_sources": {
                        "internal": {
                            "enabled": True,
                            "server": "github",
                            "arguments": {"owner": "knd3dayo", "repo": "support-ope-agents"},
                        }
                    }
                },
                "runtime": {"mode": "sample"},
                "agents": {},
            }
        )

        status = _ticket_lookup_status(
            {
                "internal_ticket_id": "2",
                "internal_ticket_lookup_enabled": True,
                "intake_ticket_context_summary": {},
                "intake_ticket_artifacts": {},
                "agent_errors": [],
            },
            config=config,
            ticket_kind="internal",
        )

        self.assertEqual(status, "enabled: true だがfetch不可: MCP manifest 未設定")

    def test_sequence_diagram_reflects_reinvestigation_route(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "draft_review_iterations": 2,
            "approval_decision": "reinvestigate",
        }

        diagram = _build_sequence_diagram(state)

        self.assertEqual(diagram.count("Investigate-->>Supervisor: 調査要約とドラフトを返却"), 3)
        self.assertIn("Approval->>Supervisor: 再調査を依頼", diagram)
        self.assertNotIn("Approval->>TicketUpdate", diagram)

    def test_sequence_diagram_reflects_escalation_reject_route_via_supervisor(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "escalation_required": True,
            "approval_decision": "reject",
        }

        diagram = _build_sequence_diagram(state)

        self.assertIn("Escalation-->>Supervisor: エスカレーション要約を返却", diagram)
        self.assertIn("Supervisor->>Inquiry: 問い合わせ文案作成を依頼", diagram)
        self.assertIn("Approval->>Supervisor: 差戻しを依頼", diagram)
        self.assertIn("Supervisor->>Inquiry: 問い合わせ文案の修正を依頼", diagram)
        self.assertNotIn("Escalation->>Inquiry", diagram)

    def test_sequence_diagram_uses_runtime_audit_roles_for_participants(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "draft_review_iterations": 1,
        }

        diagram = _build_sequence_diagram(
            state,
            runtime_audit={
                "summary": {"approval_route": "__end__"},
                "workflow_path": [
                    "receive_case",
                    "intake_prepare",
                    "intake_mask",
                    "intake_hydrate_tickets",
                    "intake_classify",
                    "intake_finalize",
                    "investigation",
                    "draft_review",
                    "wait_for_approval",
                ],
                "used_roles": [
                    "IntakeAgent",
                    "SuperVisorAgent",
                    "InvestigateAgent",
                    "ApprovalAgent",
                ],
            },
        )

        self.assertIn("participant Investigate as InvestigateAgent", diagram)
        self.assertNotIn("participant TicketUpdate as TicketUpdateAgent", diagram)
        self.assertNotIn("participant Escalation as BackSupportEscalationAgent", diagram)
        self.assertNotIn("Supervisor->>LogAnalyzer: ログ解析を依頼", diagram)

    def test_extract_instruction_criteria_returns_expected_rubric(self) -> None:
        criteria = _extract_instruction_criteria(
            """## 評価方針
- 質問内容を確認して、「ユーザーが何を知りたいか？」などを解釈してください。
- 出力の有無だけでなく、次工程に必要な情報が shared memory に反映されているかを確認してください。
- 各エージェントの working memory にしか存在しない重要情報は、伝達漏れリスクとして扱ってください。
- SuperVisorAgent の判断が最終状態と整合していても、根拠不足や記録不足があれば減点してください。
- 可能な限り、Summary、Adopted sources、Intake category、Intake urgency、Incident timeframe などの構造化項目単位で確認してください。
""",
            [],
        )

        keys = [item.key for item in criteria]
        self.assertEqual(
            keys,
            [
                "question_intent",
                "shared_memory",
                "working_memory_handoff",
                "supervisor_judgement",
                "structured_fields",
            ],
        )

    def test_subgraph_sequence_diagrams_use_customer_input_branch(self) -> None:
        state: CaseState = {
            "workflow_kind": "ambiguous_case",
            "status": "WAITING_CUSTOMER_INPUT",
            "intake_category": "ambiguous_case",
        }

        diagrams = _build_subgraph_sequence_diagrams(state)
        intake_diagram = next(item for item in diagrams if item.title == "IntakeAgent サブグラフ")

        self.assertIn("Decision->>RequestInput: 追加確認ルートへ分岐", intake_diagram.diagram)
        self.assertIn("RequestInput-->>User: 追加情報を依頼", intake_diagram.diagram)
        self.assertEqual(len(diagrams), 1)

    def test_subgraph_sequence_diagrams_reflect_rejected_review_loop(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "draft_review_iterations": 1,
            "approval_decision": "reject",
        }

        diagrams = _build_subgraph_sequence_diagrams(state)
        draft_diagram = next(item for item in diagrams if item.title == "Draft Review ループ")

        self.assertEqual(draft_diagram.diagram.count("調査要約とドラフトを返却"), 2)
        self.assertIn("participant Approval as ApprovalAgent", draft_diagram.diagram)
        self.assertIn("Approval->>Supervisor: 差戻し判断を返却", draft_diagram.diagram)

    def test_subgraph_sequence_diagrams_use_runtime_audit_path_iterations(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "draft_review_iterations": 1,
        }

        diagrams = _build_subgraph_sequence_diagrams(
            state,
            runtime_audit={
                "summary": {"approval_route": "investigation"},
                "workflow_path": [
                    "receive_case",
                    "intake_prepare",
                    "intake_mask",
                    "intake_hydrate_tickets",
                    "intake_classify",
                    "intake_finalize",
                    "investigation",
                    "draft_review",
                    "wait_for_approval",
                    "draft_review",
                    "wait_for_approval",
                ],
            },
        )
        draft_diagram = next(item for item in diagrams if item.title == "Draft Review ループ")

        self.assertEqual(draft_diagram.diagram.count("調査要約とドラフトを返却"), 2)
        self.assertIn("Approval->>Supervisor: 再調査判断を返却", draft_diagram.diagram)

    def test_subgraph_sequence_diagrams_reflect_escalation_reject_via_supervisor(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "escalation_required": True,
            "approval_decision": "reject",
        }

        diagrams = _build_subgraph_sequence_diagrams(state)
        escalation_diagram = next(item for item in diagrams if item.title == "Escalation 準備フロー")

        self.assertIn("Approval->>Supervisor: 文案差戻しを返却", escalation_diagram.diagram)
        self.assertIn("Supervisor->>Inquiry: 修正版問い合わせ文案を依頼", escalation_diagram.diagram)
        self.assertNotIn("Approval->>Inquiry: 文案差戻しを返却", escalation_diagram.diagram)

    def test_build_objective_evaluation_filters_false_positive_improvement_points(self) -> None:
        structured_evaluation = SimpleNamespace(
            criterion_evaluations=[
                SimpleNamespace(
                    criterion_key="shared_memory",
                    title="shared memory への情報反映",
                    viewpoint="次工程に必要な情報が shared memory に反映され、後続処理が参照できる状態かを確認する。",
                    result="shared memory に基本的な情報は反映されているが、ポリシー根拠の取得が未完了であることが明示されておらず、次工程での参照に不安が残る。",
                    score=60,
                    related_checklist_items=[],
                ),
                SimpleNamespace(
                    criterion_key="working_memory_handoff",
                    title="working memory 起因の伝達漏れ",
                    viewpoint="各エージェントの working memory にしか存在しない重要情報は、伝達漏れリスクとして扱ってください。",
                    result="IntakeAgent の working memory に問い合わせ分類と緊急度が記録されておらず、情報の伝達漏れが発生している。",
                    score=55,
                    related_checklist_items=[],
                ),
                SimpleNamespace(
                    criterion_key="supervisor_judgement",
                    title="SuperVisorAgent 判断の妥当性",
                    viewpoint="SuperVisorAgent の判断が最終状態と整合し、判断根拠や記録不足がないかを確認する。",
                    result="SuperVisorAgent の判断は最終状態と整合しているが、ポリシー根拠の取得が未完了であることが明示されていない。",
                    score=60,
                    related_checklist_items=[],
                ),
            ],
            agent_evaluations=[],
            improvement_points=[
                "ポリシー根拠の取得が未完了であることを shared memory に明示し、次工程での参照に備える。",
                "IntakeAgent の working memory に問い合わせ分類と緊急度を記録し、情報の追跡性を強化する。",
                "ユーザーが求める具体的な次アクションや詳細な使用方法についての情報を回答に含める。",
                "ユーザーが求める結論、原因候補、次アクションを回答本文と shared summary に明示してください。",
                "working memory にしかない重要情報は shared memory に要約転記し、引き継ぎ漏れを防いでください。",
            ],
            overall_summary="サポート対応は基本的な情報提供はできているが、ポリシー根拠の取得が未完了であることが明示されておらず、次工程での参照に不安が残る。",
            overall_score=70,
        )

        evaluation = _build_objective_evaluation(
            state={
                "workflow_kind": "specification_inquiry",
                "intake_category": "specification_inquiry",
            },
            instruction_text="## 評価方針\n- 質問内容を確認して、「ユーザーが何を知りたいか？」などを解釈してください。\n",
            shared_memory={
                "context": "- Compliance review summary: ドラフトはポリシー照合で修正が必要です。 ポリシー根拠の取得は未完了ですが、サポート担当者向けの調査回答としては継続可能と判断しました。\n- Latest compliance issues: 確認根拠となるポリシー文書を取得できませんでした。document_sources の設定と配置を確認してください。",
                "progress": "",
                "summary": "- Next action: 調査結果を回答ドラフトへ反映します。",
            },
            memory_findings=[
                MemoryConsistencyFinding(
                    agent_name="IntakeAgent",
                    severity="warning",
                    detail="問い合わせ分類 が IntakeAgent の working memory に見当たらず、処理経緯の追跡性が弱くなっています。",
                )
            ],
            structured_evaluation=structured_evaluation,
            pass_score=80,
            checklist=[],
            checklist_assessments=[],
            instruction_criteria=[],
            runtime_audit={},
            control_catalog={},
        )

        improvement_text = "\n".join(evaluation.improvement_points)
        self.assertNotIn("ポリシー根拠の取得が未完了であることを shared memory に明示", improvement_text)
        self.assertNotIn("working memory にしかない重要情報は shared memory に要約転記", improvement_text)
        self.assertNotIn("原因候補", improvement_text)
        self.assertIn("IntakeAgent の working memory に問い合わせ分類と緊急度を記録", improvement_text)
        shared_memory_criterion = next(item for item in evaluation.criterion_evaluations if item.criterion_key == "shared_memory")
        self.assertIn("context / progress に記録されています", shared_memory_criterion.result)
        working_memory_criterion = next(item for item in evaluation.criterion_evaluations if item.criterion_key == "working_memory_handoff")
        self.assertIn("伝播漏れは確認できませんでした", working_memory_criterion.result)
        self.assertIn("shared memory に記録されています", evaluation.overall_summary)


if __name__ == "__main__":
    unittest.main()