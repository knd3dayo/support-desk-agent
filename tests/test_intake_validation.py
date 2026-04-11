from __future__ import annotations

import unittest

from support_ope_agents.intake_validation import (
    resolve_effective_workflow_kind,
    validate_intake,
)


class IntakeValidationTests(unittest.TestCase):
    def test_validate_intake_requires_incident_timeframe_for_incident_cases(self) -> None:
        result = validate_intake(
            {
                "intake_category": "incident_investigation",
                "intake_urgency": "high",
            },
            {"context": "", "progress": "", "summary": ""},
        )

        self.assertEqual(result.category, "incident_investigation")
        self.assertEqual(result.urgency, "high")
        self.assertEqual(result.missing_fields, ["intake_incident_timeframe"])
        self.assertEqual(result.rework_reason, "障害発生時間帯が未確認")

    def test_validate_intake_uses_memory_snapshot_defaults(self) -> None:
        result = validate_intake(
            {},
            {
                "context": "Category: specification_inquiry\nUrgency: low\nIncident timeframe: n/a",
                "progress": "",
                "summary": "",
            },
        )

        self.assertEqual(result.category, "specification_inquiry")
        self.assertEqual(result.urgency, "low")
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.rework_reason, "")

    def test_resolve_effective_workflow_kind_prefers_specific_intake_category(self) -> None:
        resolved = resolve_effective_workflow_kind(
            {
                "workflow_kind": "ambiguous_case",
                "intake_category": "incident_investigation",
            },
            {"context": "", "progress": "", "summary": ""},
        )

        self.assertEqual(resolved, "incident_investigation")


if __name__ == "__main__":
    unittest.main()