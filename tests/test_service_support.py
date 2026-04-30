from __future__ import annotations

import unittest
from unittest.mock import patch

from support_desk_agent.runtime.service_support import normalize_state_ids


class NormalizeStateIdsTests(unittest.TestCase):
    def test_explicit_trace_id_takes_precedence(self) -> None:
        normalized = normalize_state_ids(
            {
                "trace_id": "TRACE-existing",
                "thread_id": "TRACE-thread",
                "workflow_run_id": "TRACE-run",
                "session_id": "SESSION-legacy",
            },
            trace_id="SESSION-explicit",
        )

        self.assertEqual(normalized["trace_id"], "TRACE-explicit")
        self.assertEqual(normalized["thread_id"], "TRACE-explicit")
        self.assertEqual(normalized["workflow_run_id"], "TRACE-explicit")
        self.assertNotIn("session_id", normalized)

    def test_session_id_is_used_when_trace_id_is_missing(self) -> None:
        normalized = normalize_state_ids({"case_id": "CASE-001", "session_id": "SESSION-legacy-001"})

        self.assertEqual(normalized["trace_id"], "TRACE-legacy-001")
        self.assertEqual(normalized["thread_id"], "TRACE-legacy-001")
        self.assertEqual(normalized["workflow_run_id"], "TRACE-legacy-001")
        self.assertEqual(normalized["case_id"], "CASE-001")
        self.assertNotIn("session_id", normalized)

    def test_thread_id_alone_does_not_override_generated_trace_id(self) -> None:
        with patch("support_desk_agent.runtime.service_support.new_trace_id", return_value="TRACE-generated"):
            normalized = normalize_state_ids({"thread_id": "TRACE-thread-only"})

        self.assertEqual(normalized["trace_id"], "TRACE-generated")
        self.assertEqual(normalized["thread_id"], "TRACE-generated")
        self.assertEqual(normalized["workflow_run_id"], "TRACE-generated")


if __name__ == "__main__":
    unittest.main()