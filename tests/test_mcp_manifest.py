from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.config import McpConfigError, McpManifest


class McpManifestTests(unittest.TestCase):
    def test_load_resolves_stdio_server_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "mcp.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "github": {
                                "command": "~/bin/mcp-github",
                                "args": ["${HOME}/workspace"],
                                "env": {"GITHUB_TOKEN": "os.environ/GITHUB_TOKEN"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GITHUB_TOKEN": "ghs_test_value", "HOME": "/home/test-user"}, clear=False):
                manifest = McpManifest.load(manifest_path)

        server = manifest.servers["github"]
        self.assertEqual(server.transport, "stdio")
        self.assertEqual(server.command, "/home/test-user/bin/mcp-github")
        self.assertEqual(server.args, ("/home/test-user/workspace",))
        self.assertEqual(server.env, {"GITHUB_TOKEN": "ghs_test_value"})

    def test_load_rejects_unset_env_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "mcp.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "github": {
                                "command": "mcp-github",
                                "env": {"GITHUB_TOKEN": "os.environ/GITHUB_TOKEN"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(McpConfigError, "references unset env var 'GITHUB_TOKEN'"):
                    McpManifest.load(manifest_path)

    def test_load_rejects_missing_transport_and_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "mcp.json"
            manifest_path.write_text(
                json.dumps({"mcpServers": {"github": {}}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(McpConfigError, "missing transport type"):
                McpManifest.load(manifest_path)


if __name__ == "__main__":
    unittest.main()