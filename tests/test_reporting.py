from __future__ import annotations

from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.reporting import MemoryConsistencyFinding, _build_objective_evaluation, _build_sequence_diagram, _build_subgraph_sequence_diagrams, _extract_instruction_criteria, _render_compliance_review_history
from support_ope_agents.workflow.state import CaseState


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

    def test_sequence_diagram_reflects_reinvestigation_route(self) -> None:
        state: CaseState = {
            "workflow_kind": "incident_investigation",
            "intake_category": "incident_investigation",
            "draft_review_iterations": 2,
            "approval_decision": "reinvestigate",
        }

        diagram = _build_sequence_diagram(state)

        self.assertEqual(diagram.count("DraftWriter-->>Supervisor: ドラフトを返却"), 2)
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
                    "KnowledgeRetrieverAgent",
                    "DraftWriterAgent",
                    "ComplianceReviewerAgent",
                    "ApprovalAgent",
                ],
            },
        )

        self.assertIn("participant Knowledge as KnowledgeRetrieverAgent", diagram)
        self.assertNotIn("participant LogAnalyzer as LogAnalyzerAgent", diagram)
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

        self.assertIn("Finalize-->>User: 追加情報を依頼", intake_diagram.diagram)
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

        self.assertEqual(draft_diagram.diagram.count("ドラフトを返却"), 2)
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

        self.assertEqual(draft_diagram.diagram.count("ドラフトを返却"), 2)
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

    def test_render_compliance_review_history_lists_findings_and_responses(self) -> None:
        lines = _render_compliance_review_history(
            [
                {
                    "iteration": 1,
                    "review_focus": "断定表現の確認",
                    "addressed_revision_request": "",
                    "draft_excerpt": "初回ドラフトです。復旧を約束します。",
                    "compliance_review_summary": "断定表現の修正が必要です。",
                    "compliance_review_issues": ["復旧を断定しているため表現を弱めてください。"],
                    "compliance_revision_request": "復旧を断定せず、現時点で確認できた範囲に表現を修正してください。",
                    "passed": False,
                    "adopted_sources": ["answer_policy"],
                },
                {
                    "iteration": 2,
                    "review_focus": "断定表現の確認",
                    "addressed_revision_request": "復旧を断定せず、現時点で確認できた範囲に表現を修正してください。",
                    "draft_excerpt": "修正版ドラフトです。現時点で確認できた範囲をご案内します。",
                    "compliance_review_summary": "修正内容を確認し、レビューを通過しました。",
                    "compliance_review_issues": [],
                    "compliance_revision_request": "",
                    "passed": True,
                    "adopted_sources": ["answer_policy"],
                },
            ]
        )

        rendered = "\n".join(lines)
        self.assertIn("Review Iteration 1", rendered)
        self.assertIn("指摘内容: 復旧を断定しているため表現を弱めてください。", rendered)
        self.assertIn("対応内容: 前回の修正依頼「復旧を断定せず、現時点で確認できた範囲に表現を修正してください。」に対応し、ドラフトを「修正版ドラフトです。現時点で確認できた範囲をご案内します。」へ更新しました。 最終的に 修正内容を確認し、レビューを通過しました。", rendered)
        self.assertIn("採用した根拠ソース: answer_policy", rendered)

    def test_render_compliance_review_history_summarizes_non_actionable_pass(self) -> None:
        lines = _render_compliance_review_history(
            [
                {
                    "iteration": 1,
                    "review_focus": "障害原因の断定過剰や不要な復旧約束がないかを重点確認する",
                    "addressed_revision_request": "",
                    "draft_excerpt": "お客様各位 現在、システムのログを解析した結果、いくつかの例外が検出されました。",
                    "compliance_review_summary": "ドラフトはポリシー照合で修正が必要です。 ポリシー根拠の取得は未完了ですが、顧客向けの直接回答としては継続可能と判断しました。",
                    "compliance_review_issues": ["確認根拠となるポリシー文書を取得できませんでした。"],
                    "compliance_revision_request": "確認根拠となるポリシー文書を取得できませんでした。",
                    "passed": True,
                    "adopted_sources": [],
                }
            ]
        )

        rendered = "\n".join(lines)
        self.assertIn("具体的な文面修正は行わず、レビュー結果を踏まえて顧客向けの直接回答として継続可能と判断しました。", rendered)

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