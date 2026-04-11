from __future__ import annotations

import unittest

from pydantic import ValidationError

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.reporting import _build_sequence_diagram, _build_subgraph_sequence_diagrams
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


if __name__ == "__main__":
    unittest.main()