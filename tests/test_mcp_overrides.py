from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.config.models import McpToolBinding
from support_ope_agents.tools.mcp_overrides import McpManifest, McpToolClient


class McpToolClientTests(unittest.TestCase):
    def test_build_handler_merges_static_and_mapped_arguments(self) -> None:
        client = McpToolClient(McpManifest(path=Path("manifest.json"), servers={}))

        async def _fake_call(server_name: str, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
            self.assertEqual(server_name, "github")
            self.assertEqual(tool_name, "get_issue")
            return arguments

        with patch.object(client, "_call_tool_async", side_effect=_fake_call):
            handler = client.build_handler(
                McpToolBinding(server="github", tool="get_issue"),
                logical_tool_name="external_ticket",
                static_arguments={"owner": "acme", "repo": "external-support"},
                argument_map={"ticket_id": "issue_number"},
                integer_arguments=("issue_number",),
            )
            result = asyncio.run(handler(ticket_id="123"))

        self.assertEqual(
            json.loads(result),
            {"owner": "acme", "repo": "external-support", "issue_number": 123},
        )

    def test_build_handler_rejects_non_numeric_integer_argument(self) -> None:
        client = McpToolClient(McpManifest(path=Path("manifest.json"), servers={}))
        handler = client.build_handler(
            McpToolBinding(server="github", tool="get_issue"),
            logical_tool_name="external_ticket",
            argument_map={"ticket_id": "issue_number"},
            integer_arguments=("issue_number",),
        )

        with self.assertRaisesRegex(ValueError, "requires integer argument 'issue_number'"):
            asyncio.run(handler(ticket_id="issue-123"))


if __name__ == "__main__":
    unittest.main()