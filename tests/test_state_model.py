from __future__ import annotations

import unittest

from support_desk_agent.models.state import CaseStateModel


class CaseStateModelTests(unittest.TestCase):
    def test_model_normalizes_legacy_session_id(self) -> None:
        state = CaseStateModel.model_validate({"case_id": "CASE-001", "session_id": "SESSION-legacy-001"})

        self.assertEqual(state.trace_id, "TRACE-legacy-001")
        self.assertEqual(state.thread_id, "TRACE-legacy-001")
        self.assertEqual(state.workflow_run_id, "TRACE-legacy-001")

    def test_model_preserves_existing_trace_family(self) -> None:
        state = CaseStateModel.model_validate({"trace_id": "TRACE-001", "thread_id": "THREAD-ignored"})

        self.assertEqual(state.trace_id, "TRACE-001")
        self.assertEqual(state.thread_id, "TRACE-001")
        self.assertEqual(state.workflow_run_id, "TRACE-001")

    def test_to_state_dict_omits_none_fields(self) -> None:
        state = CaseStateModel.model_validate({"case_id": "CASE-001", "workspace_path": "/tmp/work"})

        self.assertEqual(
            state.to_state_dict(),
            {
                "case_id": "CASE-001",
                "workspace_path": "/tmp/work",
            },
        )


if __name__ == "__main__":
    unittest.main()