from __future__ import annotations

import unittest

from pydantic import ValidationError

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.reporting import _build_sequence_diagram, _build_subgraph_sequence_diagrams, _render_compliance_review_history
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
        self.assertIn("Approval->>Supervisor: 差戻し判断を返却", draft_diagram.diagram)

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


if __name__ == "__main__":
    unittest.main()