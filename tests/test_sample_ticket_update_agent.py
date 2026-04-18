from __future__ import annotations

import unittest

from support_ope_agents.agents.sample.sample_ticket_update_agent import SampleTicketUpdateAgent


class SampleTicketUpdateAgentTests(unittest.TestCase):
    def test_prepare_update_uses_prepare_tool_payload(self) -> None:
        calls: list[dict[str, object]] = []

        def _prepare_ticket_update(**kwargs: object) -> str:
            calls.append(kwargs)
            return "prepared payload from tool"

        agent = SampleTicketUpdateAgent(
            prepare_ticket_update_tool=_prepare_ticket_update,
            zendesk_reply_tool=lambda **_: "zendesk updated",
            redmine_update_tool=lambda **_: "redmine updated",
        )

        result = agent.prepare_update(
            {
                "case_id": "CASE-001",
                "workspace_path": "/tmp/case",
                "external_ticket_id": "EXT-1",
                "internal_ticket_id": "INT-1",
                "draft_response": "customer draft",
            }
        )

        self.assertEqual(result["ticket_update_payload"], "prepared payload from tool")
        self.assertEqual(calls[0]["draft_response"], "customer draft")

    def test_execute_update_skips_external_without_approval(self) -> None:
        external_calls: list[dict[str, object]] = []
        internal_calls: list[dict[str, object]] = []

        agent = SampleTicketUpdateAgent(
            prepare_ticket_update_tool=lambda **_: "prepared payload",
            zendesk_reply_tool=lambda **kwargs: external_calls.append(kwargs) or "zendesk updated",
            redmine_update_tool=lambda **kwargs: internal_calls.append(kwargs) or "redmine updated",
        )

        result = agent.execute_update(
            {
                "case_id": "CASE-001",
                "workspace_path": "/tmp/case",
                "ticket_update_payload": "prepared payload",
                "external_ticket_id": "EXT-1",
                "internal_ticket_id": "INT-1",
                "approval_decision": "pending",
            }
        )

        self.assertEqual(external_calls, [])
        self.assertEqual(len(internal_calls), 1)
        self.assertIn("external:skipped approval required", result["ticket_update_result"])
        self.assertIn("internal:redmine updated", result["ticket_update_result"])

    def test_execute_update_runs_external_after_approval(self) -> None:
        external_calls: list[dict[str, object]] = []

        agent = SampleTicketUpdateAgent(
            prepare_ticket_update_tool=lambda **_: "prepared payload",
            zendesk_reply_tool=lambda **kwargs: external_calls.append(kwargs) or "zendesk updated",
            redmine_update_tool=lambda **_: "redmine updated",
        )

        result = agent.execute_update(
            {
                "case_id": "CASE-001",
                "workspace_path": "/tmp/case",
                "ticket_update_payload": "prepared payload",
                "external_ticket_id": "EXT-1",
                "approval_decision": "approved",
            }
        )

        self.assertEqual(len(external_calls), 1)
        self.assertEqual(external_calls[0]["ticket_id"], "EXT-1")
        self.assertIn("external:zendesk updated", result["ticket_update_result"])


if __name__ == "__main__":
    unittest.main()