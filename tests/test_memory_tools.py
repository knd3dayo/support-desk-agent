from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support_desk_agent.agents.roles import KNOWLEDGE_RETRIEVER_AGENT
from support_desk_agent.config.models import AppConfig
from support_desk_agent.memory.file_store import CaseMemoryStore
from support_desk_agent.tools.case_memory_manager import CaseMemoryManager
from support_desk_agent.tools.default_write_draft import build_default_write_draft_tool


class MemoryToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self._tmpdir.name)
        self.config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_case_memory_store_restricts_workspace_paths_to_case_root(self) -> None:
        store = CaseMemoryStore(self.config)
        store.initialize_case("CASE-TEST-005", str(self.workspace_path))

        with self.assertRaises(ValueError):
            store.resolve_workspace_path("CASE-TEST-005", str(self.workspace_path), "../outside.txt")

    def test_case_memory_store_lists_and_reads_workspace_files(self) -> None:
        store = CaseMemoryStore(self.config)
        store.initialize_case("CASE-TEST-006", str(self.workspace_path))
        store.write_workspace_file("CASE-TEST-006", str(self.workspace_path), "notes/example.txt", "hello world".encode("utf-8"))

        entries = store.list_workspace_entries("CASE-TEST-006", str(self.workspace_path), "notes")

        self.assertEqual(entries[0]["name"], "example.txt")
        self.assertEqual(entries[0]["kind"], "file")
        self.assertEqual(store.read_workspace_text("CASE-TEST-006", str(self.workspace_path), "notes/example.txt"), "hello world")

    def test_case_memory_store_appends_and_reads_chat_history(self) -> None:
        store = CaseMemoryStore(self.config)
        store.initialize_case("CASE-TEST-007", str(self.workspace_path))
        store.append_chat_history(
            "CASE-TEST-007",
            str(self.workspace_path),
            {"role": "user", "content": "最初の問い合わせ", "trace_id": "trace-1"},
        )
        store.append_chat_history(
            "CASE-TEST-007",
            str(self.workspace_path),
            {"role": "assistant", "content": "回答案です", "trace_id": "trace-1"},
        )

        history = store.read_chat_history("CASE-TEST-007", str(self.workspace_path))

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["content"], "回答案です")

    async def test_write_working_memory_creates_agent_working_file(self) -> None:
        case_memory_manager = CaseMemoryManager(self.config)
        tool = case_memory_manager.build_default_write_working_memory_tool(KNOWLEDGE_RETRIEVER_AGENT)

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

    async def test_read_working_memory_returns_agent_working_file_content(self) -> None:
        case_memory_manager = CaseMemoryManager(self.config)
        write_tool = case_memory_manager.build_default_write_working_memory_tool(KNOWLEDGE_RETRIEVER_AGENT)
        read_tool = case_memory_manager.build_default_read_working_memory_tool(KNOWLEDGE_RETRIEVER_AGENT)

        await write_tool(
            "CASE-TEST-008",
            str(self.workspace_path),
            {"title": "Knowledge Retrieval Result", "bullets": ["Summary: architecture overview"]},
            "append",
        )

        raw = await read_tool("CASE-TEST-008", str(self.workspace_path))

        parsed = json.loads(raw)
        self.assertEqual(parsed["agent_name"], KNOWLEDGE_RETRIEVER_AGENT)
        self.assertTrue(Path(parsed["working_memory_path"]).exists())
        self.assertIn("# Working Memory: KnowledgeRetrieverAgent", parsed["content"])
        self.assertIn("Summary: architecture overview", parsed["content"])

    async def test_write_working_memory_returns_error_payload_for_invalid_workspace_path(self) -> None:
        case_memory_manager = CaseMemoryManager(self.config)
        tool = case_memory_manager.build_default_write_working_memory_tool(KNOWLEDGE_RETRIEVER_AGENT)

        raw = await tool(
            "CASE-TEST-INVALID-001",
            "/docs/workspace-evidence/vdp.log",
            {"title": "Knowledge Retrieval Result", "bullets": ["Summary: architecture overview"]},
            "append",
        )

        parsed = json.loads(raw)
        self.assertEqual(parsed["agent_name"], KNOWLEDGE_RETRIEVER_AGENT)
        self.assertEqual(parsed["working_memory_path"], "")
        self.assertIn("error", parsed)
        self.assertIn("workspace_path", parsed)

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