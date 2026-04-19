from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_ope_agents.agents.sample.sample_supervisor_agent import SampleSupervisorAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager


class _FakeSubAgent:
    def invoke(self, _payload: object) -> dict[str, object]:
        return {"output": "ドキュメント補足: Denodo の一般的な構成説明です。"}


class _WorkspaceAwareInvestigateExecutor:
    def execute(self, *, query: str, workspace_path: str | None = None) -> dict[str, object]:
        del query
        return {"output": f"workspace={workspace_path or 'missing'}"}


class _CapturingInvestigateExecutor:
    def __init__(self) -> None:
        self.query: str = ""
        self.instruction_text: str = ""
        self.workspace_path: str | None = None

    def execute(
        self,
        *,
        query: str,
        workspace_path: str | None = None,
        instruction_text: str | None = None,
    ) -> dict[str, object]:
        self.query = query
        self.instruction_text = instruction_text or ""
        self.workspace_path = workspace_path
        return {"output": "captured"}


class _CapturingSharedMemoryWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        return json.dumps({"ok": True}, ensure_ascii=False)


class SampleInvestigateAgentTests(unittest.TestCase):
    def _build_config(self) -> AppConfig:
        return AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

    def test_execute_prioritizes_workspace_log_evidence(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text(
                "2025-10-21T20:55:12 ERROR Error loading server cache data source.\n"
                "com.denodo.vdb.cache.VDBCacheException: Data source vdpcachedatasource not found\n",
                encoding="utf-8",
            )
            with patch.object(agent, "create_sub_agent", return_value=_FakeSubAgent()):
                result = agent.execute(query="このログのフォーマットを教えて", workspace_path=tmpdir)

        summary = str(result)
        self.assertIn("vdp.log", summary)
        self.assertIn("vdpcachedatasource not found", summary)
        self.assertIn("補足情報", summary)

    def test_default_instructions_prioritize_ticket_body_for_detail_questions(self) -> None:
        config = self._build_config()
        memory_store = CaseMemoryStore(config)
        loader = InstructionLoader(config, memory_store, RuntimeHarnessManager(config))

        investigate_instruction = loader.load("CASE-TEST", "InvestigateAgent")
        supervisor_instruction = loader.load("CASE-TEST", "SuperVisorAgent")

        self.assertIn("ticket 固有の背景", investigate_instruction)
        self.assertIn("内容を教えて", investigate_instruction)
        self.assertIn("取得済み ticket context", supervisor_instruction)
        self.assertIn("ticket の要点", supervisor_instruction)

    def test_supervisor_passes_workspace_path_to_sample_investigation(self) -> None:
        supervisor = SampleSupervisorAgent(investigate_executor=_WorkspaceAwareInvestigateExecutor())

        with tempfile.TemporaryDirectory() as tmpdir:
            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-SAMPLE-001",
                    "workspace_path": tmpdir,
                    "raw_issue": "このログのフォーマットを教えて",
                }
            )

        self.assertEqual(str(result.get("investigation_summary") or ""), f"workspace={tmpdir}")

    def test_supervisor_builds_ticket_aware_query_from_followup_context(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(investigate_executor=executor)

        result = supervisor.execute_investigation(
            {
                "case_id": "CASE-TEST-SAMPLE-TICKET-001",
                "workspace_path": "/tmp/sample-case",
                "raw_issue": "顧客がログイン時の 500 エラーについて問い合わせています。",
                "customer_followup_answers": {
                    "internal_ticket_confirmation": {
                        "question": "候補は Issue #2 で正しいですか?",
                        "answer": "はい。Issue #2 の件です。"
                    }
                },
                "intake_ticket_context_summary": {
                    "internal_ticket": "Issue #2: SSO ログイン時に 500 エラーが発生し、暫定回避策は再認証です。"
                },
            }
        )

        self.assertEqual(str(result.get("investigation_summary") or ""), "captured")
        self.assertIn("顧客がログイン時の 500 エラー", executor.query)
        self.assertIn("はい。Issue #2 の件です。", executor.query)
        self.assertIn("Issue #2: SSO ログイン時に 500 エラー", executor.query)

    def test_supervisor_passes_loaded_instruction_text_to_investigation(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(
            investigate_executor=executor,
            load_instruction=lambda case_id, role: f"instruction:{case_id}:{role}",
        )

        supervisor.execute_investigation(
            {
                "case_id": "CASE-TEST-SAMPLE-INSTRUCTION-001",
                "workspace_path": "/tmp/sample-case",
                "raw_issue": "チケットの状況を確認したいです。",
            }
        )

        self.assertIn("instruction:CASE-TEST-SAMPLE-INSTRUCTION-001", executor.instruction_text)

    def test_supervisor_reads_and_updates_shared_memory_for_ticket_followup(self) -> None:
        executor = _CapturingInvestigateExecutor()
        writer = _CapturingSharedMemoryWriter()
        supervisor = SampleSupervisorAgent(
            investigate_executor=executor,
            read_shared_memory_tool=lambda **_kwargs: json.dumps(
                {
                    "context": "既知事実: 認証基盤で再現あり",
                    "progress": "前回調査: 候補チケットを確認中",
                    "summary": "Issue #2 が有力候補",
                },
                ensure_ascii=False,
            ),
            write_shared_memory_tool=writer,
        )

        result = supervisor.execute_investigation(
            {
                "case_id": "CASE-TEST-SAMPLE-MEMORY-001",
                "workspace_path": "/tmp/sample-case",
                "raw_issue": "ログイン時の 500 エラーについて調査してください。",
                "customer_followup_answers": {
                    "internal_ticket_confirmation": {
                        "question": "候補は Issue #2 で正しいですか?",
                        "answer": "はい。Issue #2 で合っています。",
                    }
                },
                "intake_ticket_context_summary": {
                    "internal_ticket": "Issue #2: SSO ログイン時に 500 エラーが発生し、再認証で一時回避できます。"
                },
            }
        )

        self.assertEqual(str(result.get("investigation_summary") or ""), "captured")
        self.assertIn("Issue #2 が有力候補", executor.query)
        self.assertIn("認証基盤で再現あり", executor.query)
        self.assertEqual(len(writer.calls), 1)
        written = writer.calls[0]
        self.assertEqual(str(written.get("case_id") or ""), "CASE-TEST-SAMPLE-MEMORY-001")
        self.assertEqual(str(written.get("mode") or ""), "replace")
        self.assertIn("captured", json.dumps(written.get("summary_content"), ensure_ascii=False))
        self.assertIn("Intake category:", json.dumps(written.get("context_content"), ensure_ascii=False))
        self.assertIn("Intake urgency:", json.dumps(written.get("progress_content"), ensure_ascii=False))
        self.assertIn("Judgment rationale:", json.dumps(written.get("summary_content"), ensure_ascii=False))
        self.assertIn("Next action:", json.dumps(written.get("summary_content"), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()