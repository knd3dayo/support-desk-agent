from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.tools.doc_generator import export_tool_docs


class ToolDocsGeneratorTests(unittest.TestCase):
    def test_export_tool_docs_writes_role_markdown_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = export_tool_docs(
                "/home/user/source/repos/support-ope-agents/config.yml",
                tmpdir,
            )

            self.assertTrue(generated)
            supervisor_doc = Path(tmpdir) / "super-visor-tools.generated.md"
            self.assertTrue(supervisor_doc.exists())
            content = supervisor_doc.read_text(encoding="utf-8")
            self.assertIn("# SuperVisorAgent ツール下書き", content)
            self.assertIn("read_shared_memory", content)
            self.assertIn("write_shared_memory", content)
            self.assertIn("## 手編集メモ", content)


if __name__ == "__main__":
    unittest.main()