from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.tools.doc_generator import export_tool_docs


class ToolDocsGeneratorTests(unittest.TestCase):
    def test_export_tool_docs_writes_per_tool_markdown_drafts_and_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stale = Path(tmpdir) / "super-visor-tools.generated.md"
            stale.write_text("stale", encoding="utf-8")

            generated = export_tool_docs(
                "/home/user/source/repos/support-ope-agents/config.yml",
                tmpdir,
            )

            self.assertTrue(generated)
            self.assertFalse(stale.exists())
            read_shared_memory_doc = Path(tmpdir) / "read_shared_memory.generated.md"
            self.assertTrue(read_shared_memory_doc.exists())
            content = read_shared_memory_doc.read_text(encoding="utf-8")
            self.assertIn("# read_shared_memory ツール下書き", content)
            self.assertIn("SuperVisorAgent", content)
            self.assertIn("BackSupportEscalationAgent", content)
            self.assertIn("## 手編集メモ", content)


if __name__ == "__main__":
    unittest.main()