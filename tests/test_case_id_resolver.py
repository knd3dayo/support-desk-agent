from __future__ import annotations

import unittest

from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService


class CaseIdResolverServiceTests(unittest.TestCase):
    def test_generates_trace_linked_ticket_ids_when_not_explicit(self) -> None:
        resolver = CaseIdResolverService()

        self.assertEqual(
            resolver.resolve_external_ticket_id(trace_id="TRACE-abc123"),
            "EXT-TRACE-abc123",
        )
        self.assertEqual(
            resolver.resolve_internal_ticket_id(trace_id="TRACE-abc123"),
            "INT-TRACE-abc123",
        )

    def test_prefers_explicit_ticket_ids(self) -> None:
        resolver = CaseIdResolverService()

        self.assertEqual(resolver.resolve_external_ticket_id(explicit_ticket_id="ext-001"), "EXT-001")
        self.assertEqual(resolver.resolve_internal_ticket_id(explicit_ticket_id="int-001"), "INT-001")


if __name__ == "__main__":
    unittest.main()