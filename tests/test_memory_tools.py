from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool
from support_ope_agents.tools.default_write_working_memory import build_default_write_working_memory_tool


class MemoryToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self._tmpdir.name)
        self.config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    async def test_write_working_memory_creates_agent_working_file(self) -> None:
        tool = build_default_write_working_memory_tool(self.config, KNOWLEDGE_RETRIEVER_AGENT)

        raw = await tool(
            "CASE-TEST-003",
            str(self.workspace_path),
            {"title": "Knowledge Retrieval Result", "bullets": ["Summary: architecture overview"]},
            "append",
        )

        parsed = json.loads(raw)
        working_path = Path(parsed["working_memory_path"])
        self.assertTrue(working_path.exists())
        content = working_path.read_text(encoding="utf-8")
        self.assertIn("# Working Memory: KnowledgeRetrieverAgent", content)
        self.assertIn("## Knowledge Retrieval Result", content)
        self.assertIn("Summary: architecture overview", content)

    async def test_write_draft_writes_markdown_artifact(self) -> None:
        tool = build_default_write_draft_tool(self.config, "customer_response_draft")

        raw = await tool(
            "CASE-TEST-004",
            str(self.workspace_path),
            {"title": "Customer Draft", "summary": "回答ドラフト本文です。"},
            "replace",
        )

        parsed = json.loads(raw)
        draft_path = Path(parsed["draft_path"])
        self.assertTrue(draft_path.exists())
        content = draft_path.read_text(encoding="utf-8")
        self.assertIn("# Customer Draft", content)
        self.assertIn("回答ドラフト本文です。", content)


if __name__ == "__main__":
    unittest.main()