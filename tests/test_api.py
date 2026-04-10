from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from support_ope_agents.interfaces.api import create_app


class ApiWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.cases_root = self.repo_root / "work" / "cases"
        self.case_path = self.cases_root / "CASE-API-001"
        self.case_path.mkdir(parents=True, exist_ok=True)
        (self.case_path / ".support-ope-case-id").write_text("CASE-API-001\n", encoding="utf-8")
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
        self.client = TestClient(create_app(str(config_path)))
        secure_config_path = self.repo_root / "secure-config.yml"
        secure_config_path.write_text(
            """
support_ope_agents:
  llm:
    provider: openai
    model: gpt-4.1
    api_key: dummy
  config_paths: {}
  data_paths: {}
  interfaces:
    auth_required: true
    auth_token: secret-token
    cors_allowed_origins:
      - http://127.0.0.1:5173
  agents: {}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        self.secure_client = TestClient(create_app(str(secure_config_path)))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_cases_endpoint_lists_workspace_cases(self) -> None:
        (self.case_path / ".support-ope-case.json").write_text(
            '{\n  "case_title": "API 調査依頼"\n}\n',
            encoding="utf-8",
        )
        response = self.client.get("/cases")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["case_id"], "CASE-API-001")
        self.assertEqual(payload[0]["case_title"], "API 調査依頼")

    def test_ui_config_endpoint_returns_display_metadata(self) -> None:
        response = self.client.get("/ui-config")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["app_name"], "Support Desk")
        self.assertFalse(payload["auth_required"])

    def test_create_case_endpoint_initializes_workspace_under_default_cases_root(self) -> None:
        response = self.client.post("/cases", json={"prompt": "CASE-API-NEW の調査を開始してください"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], "CASE-API-NEW")
        self.assertEqual(payload["case_title"], "CASE-API-NEW の調査を開始してください")
        self.assertTrue((self.cases_root / "CASE-API-NEW" / ".support-ope-case-id").exists())

    def test_workspace_upload_browse_preview_and_download(self) -> None:
        upload = self.client.post(
            "/cases/CASE-API-001/workspace/upload",
            data={"workspace_path": str(self.case_path), "relative_dir": "uploads"},
            files={"file": ("note.txt", b"api payload", "text/plain")},
        )
        browse = self.client.get(
            "/cases/CASE-API-001/workspace",
            params={"workspace_path": str(self.case_path), "path": "uploads"},
        )
        preview = self.client.get(
            "/cases/CASE-API-001/workspace/file",
            params={"workspace_path": str(self.case_path), "path": "uploads/note.txt"},
        )
        download = self.client.get(
            "/cases/CASE-API-001/workspace/download",
            params={"workspace_path": str(self.case_path)},
        )

        self.assertEqual(upload.status_code, 200)
        self.assertEqual(upload.json()["path"], "uploads/note.txt")
        self.assertEqual(browse.status_code, 200)
        self.assertEqual(browse.json()["entries"][0]["name"], "note.txt")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["content"], "api payload")
        self.assertEqual(download.status_code, 200)

        archive_path = self.case_path / "report" / "CASE-API-001-workspace.zip"
        self.assertTrue(archive_path.exists())
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("CASE-API-001/uploads/note.txt", archive.namelist())

    def test_workspace_raw_uses_inline_markdown_media_type(self) -> None:
        target = self.case_path / "report.md"
        target.write_text("# heading\n", encoding="utf-8")

        response = self.client.get(
            "/cases/CASE-API-001/workspace/raw",
            params={"workspace_path": str(self.case_path), "path": "report.md"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers.get("content-type") or "")
        self.assertIn("inline", response.headers.get("content-disposition") or "")

    def test_auth_blocks_requests_without_token(self) -> None:
        response = self.secure_client.get("/cases")

        self.assertEqual(response.status_code, 401)

    def test_auth_accepts_bearer_token_and_sets_cors_header(self) -> None:
        response = self.secure_client.get(
            "/cases",
            headers={
                "Authorization": "Bearer secret-token",
                "Origin": "http://127.0.0.1:5173",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")


if __name__ == "__main__":
    unittest.main()