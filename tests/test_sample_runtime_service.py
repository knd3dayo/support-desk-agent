from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.agents.sample.sample_intake_agent import SampleIntakeAgent
from support_ope_agents.agents.sample.sample_intake_agent import SampleIntakeClassification
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.runtime.sample.sample_service import SampleRuntimeContext
from support_ope_agents.runtime.sample.sample_service import SampleRuntimeService
from support_ope_agents.tools import ToolRegistry


class _FakeStructuredClassifier:
    def with_structured_output(self, _schema: object) -> "_FakeStructuredClassifier":
        return self

    def invoke(self, _messages: object) -> SampleIntakeClassification:
        return SampleIntakeClassification(
            category="ambiguous_case",
            urgency="medium",
            investigation_focus="候補チケットと追加確認内容を突き合わせる",
            reason="test fixture",
        )


class _DeterministicInvestigateExecutor:
    def execute(
        self,
        *,
        query: str,
        workspace_path: str | None = None,
        instruction_text: str | None = None,
    ) -> dict[str, object]:
        del workspace_path, instruction_text
        return {"output": f"確認結果: {query}"}


class SampleRuntimeServiceFlowTests(unittest.TestCase):
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
        self.service = self._build_service(self.config)
        investigate_executor = _DeterministicInvestigateExecutor()
        self.service._investigate_executor = investigate_executor
        self.service._supervisor_executor.investigate_executor = investigate_executor

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _build_service(self, config: AppConfig) -> SampleRuntimeService:
        memory_store = CaseMemoryStore(config)
        runtime_harness_manager = RuntimeHarnessManager(config)
        context = SampleRuntimeContext(
            config,
            memory_store,
            runtime_harness_manager,
            InstructionLoader(config, memory_store, runtime_harness_manager),
            ToolRegistry(config, mcp_tool_client=None),
            CaseIdResolverService(),
        )
        return SampleRuntimeService(context)

    @staticmethod
    def _hydrate_with_ticket_followup(self: SampleIntakeAgent, state: dict[str, object]) -> dict[str, object]:
        update = dict(state)
        ticket_summary = {
            "internal_ticket": "Issue #2: SSO ログイン時に 500 エラーが発生し、再認証で一時回避できます。"
        }
        update["intake_ticket_context_summary"] = ticket_summary
        answers = dict(update.get("customer_followup_answers") or {})
        if "internal_ticket_confirmation" in answers:
            update["intake_followup_questions"] = {}
        else:
            update["intake_followup_questions"] = {
                "internal_ticket_confirmation": "候補は Issue #2 で正しいですか?"
            }
        return update

    def test_resume_customer_input_reflects_ticket_summary_and_updates_shared_memory(self) -> None:
        self.service._intake_executor.hydrate_ticket_contexts = types.MethodType(
            self._hydrate_with_ticket_followup,
            self.service._intake_executor,
        )

        with patch(
            "support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model",
            return_value=_FakeStructuredClassifier(),
        ):
            initial = self.service.action(
                prompt="SSO ログイン時に 500 エラーが発生します。",
                workspace_path=str(self.workspace_path),
                case_id="CASE-SAMPLE-RESUME-001",
            )

            initial_state = initial["state"]
            self.assertEqual(str(initial_state.get("status") or ""), "WAITING_CUSTOMER_INPUT")
            self.assertIn(
                "internal_ticket_confirmation",
                dict(initial_state.get("intake_followup_questions") or {}),
            )

            resumed = self.service.resume_customer_input(
                case_id="CASE-SAMPLE-RESUME-001",
                trace_id=str(initial["trace_id"]),
                workspace_path=str(self.workspace_path),
                additional_input="はい。Issue #2 の件です。",
                answer_key="internal_ticket_confirmation",
            )

        state = resumed["state"]
        self.assertEqual(str(state.get("status") or ""), "WAITING_APPROVAL")
        self.assertTrue(bool(resumed.get("requires_approval")))
        self.assertIn("Issue #2: SSO ログイン時に 500 エラー", str(state.get("investigation_summary") or ""))
        self.assertIn("はい。Issue #2 の件です。", str(state.get("draft_response") or ""))

        answers = dict(state.get("customer_followup_answers") or {})
        self.assertEqual(
            str(answers["internal_ticket_confirmation"]["answer"] or ""),
            "はい。Issue #2 の件です。",
        )

        case_paths = self.service.context.memory_store.resolve_case_paths(
            "CASE-SAMPLE-RESUME-001",
            workspace_path=str(self.workspace_path),
        )
        shared_context = case_paths.shared_context.read_text(encoding="utf-8")
        shared_summary = case_paths.shared_summary.read_text(encoding="utf-8")
        shared_progress = case_paths.shared_progress.read_text(encoding="utf-8")
        self.assertIn("Issue #2: SSO ログイン時に 500 エラー", shared_context)
        self.assertIn("Intake category:", shared_context)
        self.assertIn("Intake urgency:", shared_context)
        self.assertIn("確認結果:", shared_summary)
        self.assertIn("Judgment rationale:", shared_summary)
        self.assertIn("Next action:", shared_summary)
        self.assertIn("sample Supervisor が再評価しました", shared_progress)
        self.assertIn("Intake category:", shared_progress)

        history = self.service.context.memory_store.read_chat_history(
            "CASE-SAMPLE-RESUME-001",
            str(self.workspace_path),
        )
        self.assertEqual(str(history[-1].get("event") or ""), "resume_customer_input")
        self.assertIn("Issue #2: SSO ログイン時に 500 エラー", str(history[-1].get("content") or ""))

    def test_resume_customer_input_with_detail_request_still_advances_to_supervisor(self) -> None:
        self.service._intake_executor.hydrate_ticket_contexts = types.MethodType(
            self._hydrate_with_ticket_followup,
            self.service._intake_executor,
        )

        with patch(
            "support_ope_agents.agents.sample.sample_intake_agent.build_chat_openai_model",
            return_value=_FakeStructuredClassifier(),
        ):
            initial = self.service.action(
                prompt="SSO ログイン時に 500 エラーが発生します。",
                workspace_path=str(self.workspace_path),
                case_id="CASE-SAMPLE-RESUME-DETAIL-001",
            )

            resumed = self.service.resume_customer_input(
                case_id="CASE-SAMPLE-RESUME-DETAIL-001",
                trace_id=str(initial["trace_id"]),
                workspace_path=str(self.workspace_path),
                additional_input="内容を教えて",
                answer_key="internal_ticket_confirmation",
            )

        state = resumed["state"]
        self.assertEqual(str(state.get("status") or ""), "WAITING_APPROVAL")
        self.assertIn("Issue #2: SSO ログイン時に 500 エラー", str(state.get("draft_response") or ""))
        self.assertFalse(bool(resumed.get("requires_customer_input")))


if __name__ == "__main__":
    unittest.main()
