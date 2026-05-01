from __future__ import annotations

import unittest

from support_desk_agent.agents.roles import APPROVAL_AGENT
from support_desk_agent.agents.roles import INTAKE_AGENT
from support_desk_agent.agents.roles import SUPERVISOR_AGENT
from support_desk_agent.agents.roles import TICKET_UPDATE_AGENT
from support_desk_agent.models.state_transitions import StateTransitionHelper


class StateTransitionHelperTests(unittest.TestCase):
    def test_supervisor_investigating_sets_status_and_agent(self) -> None:
        updated = StateTransitionHelper.supervisor_investigating({"case_id": "CASE-001"})

        self.assertEqual(updated["status"], "INVESTIGATING")
        self.assertEqual(updated["current_agent"], SUPERVISOR_AGENT)
        self.assertEqual(updated["case_id"], "CASE-001")

    def test_draft_ready_sets_status_and_optional_agent(self) -> None:
        updated = StateTransitionHelper.draft_ready({"case_id": "CASE-001"}, current_agent=SUPERVISOR_AGENT)

        self.assertEqual(updated["status"], "DRAFT_READY")
        self.assertEqual(updated["current_agent"], SUPERVISOR_AGENT)
        self.assertEqual(updated["case_id"], "CASE-001")

    def test_intake_triaged_sets_status_and_agent(self) -> None:
        updated = StateTransitionHelper.intake_triaged({"raw_issue": "x"})

        self.assertEqual(updated["status"], "TRIAGED")
        self.assertEqual(updated["current_agent"], INTAKE_AGENT)

    def test_waiting_for_customer_input_sets_defaults(self) -> None:
        updated = StateTransitionHelper.waiting_for_customer_input({"case_id": "CASE-001"})

        self.assertEqual(updated["status"], "WAITING_CUSTOMER_INPUT")
        self.assertEqual(updated["current_agent"], INTAKE_AGENT)
        self.assertEqual(updated["next_action"], "IntakeAgent の質問に回答し、追加情報を提供してください。")

    def test_waiting_for_customer_input_preserves_existing_next_action(self) -> None:
        updated = StateTransitionHelper.waiting_for_customer_input(
            {"next_action": "custom"},
            next_action="fallback",
        )

        self.assertEqual(updated["status"], "WAITING_CUSTOMER_INPUT")
        self.assertEqual(updated["current_agent"], INTAKE_AGENT)
        self.assertEqual(updated["next_action"], "custom")

    def test_waiting_for_approval_for_plan_sets_plan_prompt(self) -> None:
        state = {"execution_mode": "plan"}

        updated = StateTransitionHelper.waiting_for_approval(state)

        self.assertEqual(updated["status"], "WAITING_APPROVAL")
        self.assertEqual(updated["current_agent"], APPROVAL_AGENT)
        self.assertEqual(updated["approval_decision"], "pending")
        self.assertEqual(updated["next_action"], "この計画で action を実行するか確認してください。")

    def test_waiting_for_approval_for_escalation_sets_escalation_prompt(self) -> None:
        state = {"execution_mode": "action", "escalation_required": True}

        updated = StateTransitionHelper.waiting_for_approval(state)

        self.assertEqual(updated["status"], "WAITING_APPROVAL")
        self.assertEqual(updated["current_agent"], APPROVAL_AGENT)
        self.assertEqual(updated["approval_decision"], "pending")
        self.assertEqual(updated["next_action"], "エスカレーション問い合わせ文案を確認し、送付可否を承認してください。")

    def test_waiting_for_approval_for_draft_sets_draft_prompt(self) -> None:
        state = {"execution_mode": "action", "escalation_required": False}

        updated = StateTransitionHelper.waiting_for_approval(state)

        self.assertEqual(updated["status"], "WAITING_APPROVAL")
        self.assertEqual(updated["current_agent"], APPROVAL_AGENT)
        self.assertEqual(updated["approval_decision"], "pending")
        self.assertEqual(updated["next_action"], "回答ドラフトを確認し、チケット更新を承認してください。")

    def test_ticket_update_prepared_sets_payload_and_next_action(self) -> None:
        state = {"case_id": "CASE-001", "status": "DRAFT_READY"}

        updated = StateTransitionHelper.ticket_update_prepared(
            state,
            payload="prepared payload",
            next_action="run update",
        )

        self.assertEqual(updated["case_id"], "CASE-001")
        self.assertEqual(updated["status"], "DRAFT_READY")
        self.assertEqual(updated["current_agent"], TICKET_UPDATE_AGENT)
        self.assertEqual(updated["ticket_update_payload"], "prepared payload")
        self.assertEqual(updated["next_action"], "run update")

    def test_ticket_update_completed_closes_case(self) -> None:
        state = {"case_id": "CASE-001", "status": "DRAFT_READY"}

        updated = StateTransitionHelper.ticket_update_completed(state)

        self.assertEqual(updated["case_id"], "CASE-001")
        self.assertEqual(updated["status"], "CLOSED")
        self.assertEqual(updated["current_agent"], TICKET_UPDATE_AGENT)
        self.assertEqual(updated["ticket_update_result"], "Zendesk と Redmine の更新処理を完了しました。")
        self.assertEqual(updated["next_action"], "外部チケット更新を完了しました")


if __name__ == "__main__":
    unittest.main()