from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from fastapi.testclient import TestClient

from support_ope_agents.agents.objective_evaluation_agent import (
    ObjectiveEvaluationAgent,
    ObjectiveEvaluationStructuredResult,
    StructuredAgentEvaluation,
    StructuredCriterionEvaluation,
)
from support_ope_agents.interfaces.api import create_app


def _fake_objective_evaluation_result() -> ObjectiveEvaluationStructuredResult:
    return ObjectiveEvaluationStructuredResult(
        criterion_evaluations=[
            StructuredCriterionEvaluation(
                title="質問意図への回答妥当性",
                viewpoint="最終回答が質問の主訴に対して結論を返しているか",
                result="結論は概ね返せています。",
                score=78,
            )
        ],
        agent_evaluations=[
            StructuredAgentEvaluation(agent_name="IntakeAgent", score=82, comment="入力整理は安定しています。"),
            StructuredAgentEvaluation(agent_name="KnowledgeRetrieverAgent", score=80, comment="ナレッジ参照は成立しています。"),
        ],
        overall_summary="API 経由のレポート生成に必要な評価は取得できています。",
        improvement_points=["shared summary をより簡潔に保ってください。"],
        overall_score=79,
    )


class _FakeClassifierModel:
    async def ainvoke(self, _messages):
        return AIMessage(content='{"category":"specification_inquiry","urgency":"medium","investigation_focus":"期待動作と現行仕様の差分を確認する","reason":"mocked llm classification"}')


class _FakeDraftModel:
    async def ainvoke(self, _messages):
        return AIMessage(content="お問い合わせありがとうございます。\n\n現時点の結論として、アーキテクチャ概要をご案内します。")


class _FakeComplianceModel:
    async def ainvoke(self, _messages):
        return AIMessage(content='{"summary":"mocked compliance review","issues":[]}')


class ApiWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._objective_eval_patcher = patch.object(
            ObjectiveEvaluationAgent,
            "_invoke_structured_evaluation",
            return_value=_fake_objective_evaluation_result(),
        )
        self._classify_model_patcher = patch(
            "support_ope_agents.tools.default_classify_ticket._get_chat_model",
            return_value=_FakeClassifierModel(),
        )
        self._draft_model_patcher = patch(
            "support_ope_agents.agents.draft_writer_agent._get_chat_model",
            return_value=_FakeDraftModel(),
        )
        self._compliance_model_patcher = patch(
            "support_ope_agents.tools.default_check_policy._get_chat_model",
            return_value=_FakeComplianceModel(),
        )
        self._objective_eval_patcher.start()
        self._classify_model_patcher.start()
        self._draft_model_patcher.start()
        self._compliance_model_patcher.start()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.cases_root = self.repo_root / "work" / "cases"
        self.case_path = self.cases_root / "CASE-API-001"
        self.case_path.mkdir(parents=True, exist_ok=True)
        (self.case_path / ".support-ope-case-id").write_text("CASE-API-001\n", encoding="utf-8")
        config_path = self.repo_root / "config.yml"
        config_path.write_text(
                        "\n".join([
                                "support_ope_agents:",
                                "  llm:",
                                "    provider: openai",
                                "    model: gpt-4.1",
                                "    api_key: sk-test-value",
                                "  config_paths: {}",
                                "  data_paths: {}",
                                "  interfaces: {}",
                                "  agents: {}",
                        ])
                        + "\n",
            encoding="utf-8",
        )
        self.client = TestClient(create_app(str(config_path)))
        secure_config_path = self.repo_root / "secure-config.yml"
        secure_config_path.write_text(
                        "\n".join([
                                "support_ope_agents:",
                                "  llm:",
                                "    provider: openai",
                                "    model: gpt-4.1",
                                "    api_key: sk-test-value",
                                "  config_paths: {}",
                                "  data_paths: {}",
                                "  interfaces:",
                                "    auth_required: true",
                                "    auth_token: secret-token",
                                "    cors_allowed_origins:",
                                "      - http://127.0.0.1:5173",
                                "  agents: {}",
                        ])
                        + "\n",
            encoding="utf-8",
        )
        self.secure_client = TestClient(create_app(str(secure_config_path)))

    def tearDown(self) -> None:
        self.client.close()
        self.secure_client.close()
        self._compliance_model_patcher.stop()
        self._draft_model_patcher.stop()
        self._classify_model_patcher.stop()
        self._objective_eval_patcher.stop()
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
        self.assertTrue(browse.json()["entries"][0]["updated_at"])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["content"], "api payload")
        self.assertEqual(download.status_code, 200)

        archive_path = self.case_path / ".report" / "CASE-API-001-workspace.zip"
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

    def test_generate_report_endpoint_writes_report(self) -> None:
        trace_id = "TRACE-API-001"
        self.client.post(
            "/action",
            json={
                "prompt": "生成AI基盤のアーキテクチャ概要を教えてください。",
                "workspace_path": str(self.case_path),
                "case_id": "CASE-API-001",
                "trace_id": trace_id,
            },
        )

        response = self.client.post(
            "/cases/CASE-API-001/report",
            json={
                "trace_id": trace_id,
                "workspace_path": str(self.case_path),
                "checklist": ["sequenceDiagram が含まれているか"],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        report_path = Path(payload["report_path"])
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent.name, ".report")
        content = report_path.read_text(encoding="utf-8")
        self.assertIn("sequenceDiagram", content)
        self.assertIn("## 制御一覧", content)
        self.assertIn("[defined] workflow.approval_node", content)
        self.assertIn("config_key: workflow.approval_node", content)

    def test_action_endpoint_accepts_langchain_conversation_messages(self) -> None:
        response = self.client.post(
            "/action",
            json={
                "prompt": "詳細を教えてください",
                "workspace_path": str(self.case_path),
                "case_id": "CASE-API-001",
                "conversation_messages": [
                    {
                        "type": "human",
                        "data": {
                            "content": "ai-chat-utilについて教えて",
                            "additional_kwargs": {},
                            "response_metadata": {},
                        },
                    },
                    {
                        "type": "ai",
                        "data": {
                            "content": "概要を説明します。",
                            "additional_kwargs": {},
                            "response_metadata": {},
                        },
                    },
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        raw_issue = str(payload["state"].get("raw_issue") or "")
        conversation_messages = payload["state"].get("conversation_messages") or []
        self.assertIn("ai-chat-utilについて教えて", raw_issue)
        self.assertIn("詳細を教えてください", raw_issue)
        self.assertEqual(conversation_messages[0]["type"], "human")

    def test_history_endpoint_returns_langchain_conversation_messages(self) -> None:
        self.client.post(
            "/action",
            json={
                "prompt": "生成AI基盤のアーキテクチャ概要を教えてください。",
                "workspace_path": str(self.case_path),
                "case_id": "CASE-API-001",
            },
        )

        response = self.client.get(
            "/cases/CASE-API-001/history",
            params={"workspace_path": str(self.case_path)},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["conversation_messages"])
        self.assertEqual(payload["conversation_messages"][0]["type"], "human")

    def test_action_endpoint_accepts_explicit_case_and_ticket_ids(self) -> None:
        explicit_case_path = self.cases_root / "CASE-API-EXPLICIT"

        response = self.client.post(
            "/action",
            json={
                "prompt": "内部外部チケットを参照してください。",
                "workspace_path": str(explicit_case_path),
                "case_id": "CASE-API-EXPLICIT",
                "external_ticket_id": "ext-111",
                "internal_ticket_id": "int-222",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], "CASE-API-EXPLICIT")
        self.assertEqual(payload["external_ticket_id"], "EXT-111")
        self.assertEqual(payload["internal_ticket_id"], "INT-222")
        self.assertTrue((explicit_case_path / ".support-ope-case-id").exists())

    def test_control_catalog_endpoint_returns_summary(self) -> None:
        response = self.client.get("/control-catalog")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(int(payload["summary"]["control_point_count"]), 8)
        first_point = payload["control_points"][0]
        self.assertEqual(first_point["config_key"], "workflow.approval_node")
        self.assertIn("docs/configuration.md", first_point["docs_refs"])
        self.assertIn("src/support_ope_agents/config/models.py", first_point["code_refs"])

    def test_runtime_audit_endpoint_returns_trace_audit(self) -> None:
        trace_id = "TRACE-API-AUDIT"
        self.client.post(
            "/action",
            json={
                "prompt": "生成AI基盤のアーキテクチャ概要を教えてください。",
                "workspace_path": str(self.case_path),
                "case_id": "CASE-API-001",
                "trace_id": trace_id,
            },
        )

        response = self.client.get(
            "/cases/CASE-API-001/runtime-audit",
            params={"workspace_path": str(self.case_path), "trace_id": trace_id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["trace_id"], trace_id)
        self.assertTrue(payload["workflow_path"])
        self.assertTrue(payload["decision_log"])

    def test_generate_report_endpoint_requires_auth_when_enabled(self) -> None:
        response = self.secure_client.post(
            "/cases/CASE-API-001/report",
            json={
                "trace_id": "TRACE-API-SECURE",
                "workspace_path": str(self.case_path),
                "checklist": [],
            },
        )

        self.assertEqual(response.status_code, 401)

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