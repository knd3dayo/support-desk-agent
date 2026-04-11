from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.interfaces.mcp import SupportOpeMcpAdapter


class McpAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.workspace_path = self.repo_root / "work" / "cases" / "CASE-MCP-001"
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        (self.workspace_path / ".support-ope-case-id").write_text("CASE-MCP-001\n", encoding="utf-8")
        config_path = self.repo_root / "config.yml"
        config_path.write_text(
            """
support_ope_agents:
  llm:
    provider: openai
    model: gpt-4.1
    api_key: dummy
  config_paths: {}
  data_paths: {}
  interfaces: {}
  agents: {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        self.adapter = SupportOpeMcpAdapter(str(config_path))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_manifest_includes_generate_report_tool(self) -> None:
        manifest = self.adapter.manifest()

        tool_names = {tool["name"] for tool in manifest["tools"]}
        self.assertIn("generate_report", tool_names)

    def test_generate_report_tool_writes_report(self) -> None:
        plan = self.adapter.call_tool(
            "action",
            {
                "prompt": "生成AI基盤のアーキテクチャ概要を教えてください。",
                "workspace_path": str(self.workspace_path),
            },
        )

        result = self.adapter.call_tool(
            "generate_report",
            {
                "case_id": "CASE-MCP-001",
                "trace_id": str(plan["trace_id"]),
                "workspace_path": str(self.workspace_path),
                "checklist": ["KnowledgeRetrieverAgent が含まれているか"],
            },
        )

        report_path = Path(str(result["report_path"]))
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent.name, "report")


if __name__ == "__main__":
    unittest.main()