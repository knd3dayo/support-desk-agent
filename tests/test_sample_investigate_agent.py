from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from support_desk_agent.agents.objective_evaluator import ObjectiveEvaluatorStructuredResult
from support_desk_agent.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_desk_agent.agents.sample.sample_supervisor_agent import SampleSupervisorAgent
from support_desk_agent.config.models import AppConfig
from support_desk_agent.instructions.loader import InstructionLoader
from support_desk_agent.models.state import CaseState
from support_desk_agent.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_desk_agent.workspace import CaseMemoryStore


class _FakeSubAgent:
    async def ainvoke(self, _payload: object, *, context: object | None = None) -> dict[str, object]:
        del context
        return {"output": "ドキュメント補足: Denodo の一般的な構成説明です。"}


class _FakeNoopSubAgent:
    async def ainvoke(self, _payload: object, *, context: object | None = None) -> dict[str, object]:
        del context
        return {"output": "補足なし"}


class _FakeMissingEvidenceSubAgent:
    async def ainvoke(self, _payload: object, *, context: object | None = None) -> dict[str, object]:
        del context
        return {"output": "vdp.log ファイルが見つからず、再提供が必要です。"}


class _WorkspaceAwareInvestigateExecutor:
    def execute(
        self,
        *,
        query: str,
        mode: str = "action",
        workspace_path: str | None = None,
        instruction_text: str | None = None,
        state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del query, instruction_text, state
        return {"output": f"{mode}:workspace={workspace_path or 'missing'}"}


class _CapturingInvestigateExecutor:
    def __init__(self) -> None:
        self.query: str = ""
        self.instruction_text: str = ""
        self.workspace_path: str | None = None
        self.modes: list[str] = []

    def execute(
        self,
        *,
        query: str,
        mode: str = "action",
        workspace_path: str | None = None,
        instruction_text: str | None = None,
        state: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.query = query
        self.instruction_text = instruction_text or ""
        self.workspace_path = workspace_path
        self.modes.append(mode)
        del state
        return {"output": f"captured:{mode}"}


class _CapturingSubAgent:
    def __init__(self, output: str = "captured") -> None:
        self.payloads: list[object] = []
        self.contexts: list[object | None] = []
        self.output = output

    async def ainvoke(self, payload: object, *, context: object | None = None) -> dict[str, object]:
        self.payloads.append(payload)
        self.contexts.append(context)
        return {"output": self.output}


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
        self.assertIn("Denodo の一般的な構成説明", summary)

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

    def test_execute_includes_requested_log_range_in_query_when_incident_timeframe_exists(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())
        capturing_sub_agent = _CapturingSubAgent(output="補足なし")

        with patch.object(agent, "create_sub_agent", return_value=capturing_sub_agent):
            agent.execute(
                query="ログを調べて\n\nログ抽出の手掛かり:\n- incident timeframe: 2025-10-21 20:55 頃\n- requested extract range: 2025-10-21T20:40:00 -> 2025-10-21T21:10:00\n- 必要なら infer_log_header_pattern と extract_log_time_range を使って、この時間帯のログ断片を自分で抽出してください。"
            )

        payload_text = str(capturing_sub_agent.payloads[0])
        self.assertIn("incident timeframe: 2025-10-21 20:55 頃", payload_text)
        self.assertIn("requested extract range: 2025-10-21T20:40:00 -> 2025-10-21T21:10:00", payload_text)
        self.assertIn("extract_log_time_range", payload_text)

    def test_create_sub_agent_passes_investigate_tools_to_deep_agent(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        with patch("support_desk_agent.agents.sample.sample_investigate_agent.build_filtered_document_source_backend") as backend_mock:
            with patch("support_desk_agent.agents.sample.sample_investigate_agent.create_deep_agent_compatible_agent") as create_mock:
                backend_mock.return_value = object()
                create_mock.return_value = object()
                agent.create_sub_agent(query="ログを調べて")

        tools = create_mock.call_args.kwargs["tools"]
        tool_names = [getattr(tool, "__name__", "") for tool in tools]
        self.assertIn("list_zip_contents", tool_names)
        self.assertIn("extract_zip", tool_names)
        self.assertIn("create_zip", tool_names)
        self.assertIn("detect_log_format_and_search", tool_names)
        self.assertIn("infer_log_header_pattern", tool_names)
        self.assertIn("extract_log_time_range", tool_names)
        self.assertIn("analyze_image_files", tool_names)
        self.assertIn("analyze_pdf_files", tool_names)
        self.assertIn("analyze_office_files", tool_names)
        self.assertIn("convert_office_files_to_pdf", tool_names)
        self.assertIn("convert_pdf_files_to_images", tool_names)
        self.assertIn("write_working_memory", tool_names)

    def test_create_sub_agent_wraps_async_tools_synchronously(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        async def _async_tool(*_args: object, **_kwargs: object) -> str:
            return "ok"

        fake_tool = type("FakeTool", (), {"name": "write_working_memory", "handler": _async_tool})()

        with patch.object(agent.tool_registry, "get_tools", return_value=[fake_tool]):
            with patch("support_desk_agent.agents.sample.sample_investigate_agent.build_filtered_document_source_backend") as backend_mock:
                with patch("support_desk_agent.agents.sample.sample_investigate_agent.create_deep_agent_compatible_agent") as create_mock:
                    backend_mock.return_value = object()
                    create_mock.return_value = object()
                    agent.create_sub_agent(query="ログを調べて")

        wrapped_tool = create_mock.call_args.kwargs["tools"][0]
        self.assertEqual(wrapped_tool(), "ok")

    def test_create_sub_agent_adds_workspace_evidence_to_document_sources(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            with patch("support_desk_agent.agents.sample.sample_investigate_agent.build_filtered_document_source_backend") as backend_mock:
                with patch("support_desk_agent.agents.sample.sample_investigate_agent.create_deep_agent_compatible_agent") as create_mock:
                    backend_mock.return_value = object()
                    create_mock.return_value = object()
                    agent.create_sub_agent(query="ログを調べて", workspace_path=tmpdir)

        document_sources = backend_mock.call_args.kwargs["document_sources"]
        source_names = [source.name for source in document_sources]
        self.assertIn("workspace-evidence", source_names)

    def test_create_sub_agent_enables_agents_memory_and_context_schema(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        with patch("support_desk_agent.agents.sample.sample_investigate_agent.build_filtered_document_source_backend") as backend_mock:
            with patch("support_desk_agent.agents.sample.sample_investigate_agent.create_deep_agent_compatible_agent") as create_mock:
                backend_mock.return_value = object()
                create_mock.return_value = object()
                agent.create_sub_agent(query="ドキュメントから仕様を確認して")

        memory_sources = create_mock.call_args.kwargs["memory"]
        self.assertTrue(memory_sources)
        self.assertTrue(str(memory_sources[0]).endswith("/support_desk_agent/AGENTS.md"))
        self.assertIs(create_mock.call_args.kwargs["context_schema"], CaseState)

    def test_system_prompt_instructs_checklist_memory_and_attachment_analysis(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        prompt = agent._build_system_prompt("ログを調べて")

        self.assertIn("read_working_memory", prompt)
        self.assertIn("チェックリスト", prompt)
        self.assertIn("write_working_memory", prompt)
        self.assertIn("analyze_pdf_files", prompt)
        self.assertIn("analyze_image_files", prompt)
        self.assertIn("list_zip_contents", prompt)
        self.assertIn("extract_zip", prompt)
        self.assertIn("list_zip_contents", prompt)
        self.assertIn("extract_zip", prompt)
        self.assertIn("結論", prompt)
        self.assertIn("根拠", prompt)
        self.assertIn("英語だけの回答は禁止", prompt)

    def test_plan_mode_prompt_requests_japanese_structured_plan(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        prompt = agent._build_system_prompt("ログを調べて", mode=SampleInvestigateAgent.PLAN_MODE)

        self.assertIn("計画要約", prompt)
        self.assertIn("主要ステップ", prompt)
        self.assertIn("未解決論点", prompt)

    def test_supervisor_includes_attachment_paths_and_evidence_in_query(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=executor)

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text("error line", encoding="utf-8")
            attachment_dir = Path(tmpdir) / ".artifacts" / "intake" / "external_attachments"
            attachment_dir.mkdir(parents=True, exist_ok=True)
            (attachment_dir / "guide.pdf").write_text("pdf payload", encoding="utf-8")
            (attachment_dir / "screen.png").write_text("png payload", encoding="utf-8")
            with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
                evaluate_mock.side_effect = [
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="plan ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="result ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                ]
                supervisor.execute_investigation(
                    {
                        "case_id": "CASE-TEST-SAMPLE-ATTACH-001",
                        "workspace_path": tmpdir,
                        "raw_issue": "添付を含めて調べて",
                    }
                )

        self.assertIn("Evidence file: vdp.log", executor.query)
        self.assertIn("Evidence log preview:", executor.query)
        self.assertIn("error line", executor.query)
        self.assertIn("Working memory tool parameters", executor.query)
        self.assertIn("CASE-TEST-SAMPLE-ATTACH-001", executor.query)
        self.assertIn("guide.pdf", executor.query)
        self.assertIn("screen.png", executor.query)
        self.assertIn("analyze_pdf_files", executor.query)
        self.assertIn("list_zip_contents", executor.query)
        self.assertIn("extract_zip", executor.query)

    def test_supervisor_includes_non_media_attachments_in_query(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=executor)

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "bundle.zip").write_text("zip payload", encoding="utf-8")
            with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
                evaluate_mock.side_effect = [
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="plan ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="result ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                ]
                supervisor.execute_investigation(
                    {
                        "case_id": "CASE-TEST-SAMPLE-ATTACH-ZIP-001",
                        "workspace_path": tmpdir,
                        "raw_issue": "添付を含めて調べて",
                    }
                )

        self.assertIn("bundle.zip", executor.query)

    def test_supervisor_respects_attachment_ignore_patterns(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {"attachment_ignore_patterns": ["*.tmp", ".evidence/excluded/**"]},
                "interfaces": {},
                "agents": {},
            }
        )
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(config, investigate_executor=executor)

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "visible.zip").write_text("zip payload", encoding="utf-8")
            (evidence_dir / "ignored.tmp").write_text("tmp payload", encoding="utf-8")
            excluded_dir = evidence_dir / "excluded"
            excluded_dir.mkdir(parents=True, exist_ok=True)
            (excluded_dir / "secret.log").write_text("secret", encoding="utf-8")
            with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
                evaluate_mock.side_effect = [
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="plan ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="result ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                ]
                supervisor.execute_investigation(
                    {
                        "case_id": "CASE-TEST-SAMPLE-ATTACH-IGNORE-001",
                        "workspace_path": tmpdir,
                        "raw_issue": "添付を含めて調べて",
                    }
                )

        self.assertIn("visible.zip", executor.query)
        self.assertNotIn("ignored.tmp", executor.query)
        self.assertNotIn("secret.log", executor.query)

    def test_find_evidence_log_file_uses_generic_text_log_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "custom-name.txt").write_text("hello", encoding="utf-8")

            from support_desk_agent.workspace import find_evidence_log_file

            result = find_evidence_log_file(tmpdir)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "custom-name.txt")

    def test_execute_returns_sub_agent_result_without_post_processing(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())
        capturing_sub_agent = _CapturingSubAgent(output="vdp.log ファイルが見つからず、再提供が必要です。")

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text(
                "2025-10-21T20:55:12 ERROR Error loading server cache data source.\n"
                "com.denodo.vdb.cache.VDBCacheException: Data source vdpcachedatasource not found\n",
                encoding="utf-8",
            )
            with patch.object(agent, "create_sub_agent", return_value=capturing_sub_agent):
                result = agent.execute(
                    query="ログを調べて",
                    workspace_path=tmpdir,
                    state={"investigation_evidence_log_path": str(evidence_dir / "vdp.log")},
                )

        rendered = str(result)
        self.assertIn("ログを調べて", str(capturing_sub_agent.payloads[0]))
        self.assertIn("再提供が必要", rendered)

    def test_execute_uses_plain_query_for_standalone_run(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())
        capturing_sub_agent = _CapturingSubAgent(output="補足なし")

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text("2025-10-21T20:55:12 ERROR sample\n", encoding="utf-8")
            with patch.object(agent, "create_sub_agent", return_value=capturing_sub_agent):
                agent.execute(query="ログを調べて", workspace_path=tmpdir)

        payload_text = str(capturing_sub_agent.payloads[0])
        self.assertIn("ログを調べて", payload_text)
        self.assertNotIn("Evidence file:", payload_text)

    def test_execute_passes_context_to_sub_agent(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())
        capturing_sub_agent = _CapturingSubAgent(output="補足なし")

        with patch.object(agent, "create_sub_agent", return_value=capturing_sub_agent):
            agent.execute(
                query="仕様を確認して",
                workspace_path="/tmp/sample-case",
                state={"case_id": "CASE-CTX-001"},
            )

        context = capturing_sub_agent.contexts[0]
        self.assertEqual(cast(dict[str, object], context).get("case_id"), "CASE-CTX-001")
        self.assertEqual(cast(dict[str, object], context).get("workspace_path"), "/tmp/sample-case")

    def test_execute_tolerates_attached_chat_model_cleanup_hook(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())
        capturing_sub_agent = _CapturingSubAgent(output="補足なし")
        attached_model = object()
        setattr(capturing_sub_agent, "_support_ope_chat_model", attached_model)

        with patch.object(agent, "create_sub_agent", return_value=capturing_sub_agent):
            agent.execute(query="仕様を確認して")

    def test_execute_raises_when_sub_agent_invocation_fails(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with patch.object(agent, "create_sub_agent", side_effect=RuntimeError("boom")):
                agent.execute(query="ログがなくても仕様を確認して")

    def test_supervisor_passes_workspace_path_to_sample_investigation(self) -> None:
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=_WorkspaceAwareInvestigateExecutor())

        with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
            evaluate_mock.side_effect = [
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="plan ok",
                    improvement_points=[],
                    overall_score=90,
                ),
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="result ok",
                    improvement_points=[],
                    overall_score=90,
                ),
            ]

            with tempfile.TemporaryDirectory() as tmpdir:
                result = supervisor.execute_investigation(
                    {
                        "case_id": "CASE-TEST-SAMPLE-001",
                        "workspace_path": tmpdir,
                        "raw_issue": "このログのフォーマットを教えて",
                    }
                )

        self.assertEqual(str(result.get("investigation_summary") or ""), f"action:workspace={tmpdir}")
        self.assertEqual(str(result.get("plan_summary") or ""), f"plan:workspace={tmpdir}")

    def test_supervisor_builds_ticket_aware_query_from_followup_context(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=executor)

        with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
            evaluate_mock.side_effect = [
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="plan ok",
                    improvement_points=[],
                    overall_score=90,
                ),
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="result ok",
                    improvement_points=[],
                    overall_score=90,
                ),
            ]
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

        self.assertEqual(str(result.get("investigation_summary") or ""), "captured:action")
        self.assertEqual(str(result.get("plan_summary") or ""), "captured:plan")
        self.assertIn("顧客がログイン時の 500 エラー", executor.query)
        self.assertIn("はい。Issue #2 の件です。", executor.query)
        self.assertIn("Issue #2: SSO ログイン時に 500 エラー", executor.query)
        self.assertEqual(executor.modes, ["plan", "action"])

    def test_supervisor_passes_loaded_instruction_text_to_investigation(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=executor)

        with patch(
            "support_desk_agent.agents.sample.sample_supervisor_agent.InstructionLoader.load",
            side_effect=[
                "instruction:CASE-TEST-SAMPLE-INSTRUCTION-001:SuperVisorAgent",
                "instruction:CASE-TEST-SAMPLE-INSTRUCTION-001:ObjectiveEvaluator",
                "instruction:CASE-TEST-SAMPLE-INSTRUCTION-001:ObjectiveEvaluator",
            ],
        ):
            with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
                evaluate_mock.side_effect = [
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="plan ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                    ObjectiveEvaluatorStructuredResult(
                        criterion_evaluations=[],
                        agent_evaluations=[],
                        overall_summary="result ok",
                        improvement_points=[],
                        overall_score=90,
                    ),
                ]
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
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=executor)

        def _invoke_tool(tool_name: str, role: str, **kwargs: object) -> str:
            del role
            if tool_name == "write_shared_memory":
                return writer(**kwargs)
            if tool_name == "write_working_memory":
                return json.dumps({"ok": True}, ensure_ascii=False)
            raise AssertionError(f"unexpected tool_name: {tool_name}")

        with patch.object(
            supervisor.tool_registry,
            "read_shared_memory_for_case",
            return_value={
                "context": "既知事実: 認証基盤で再現あり",
                "progress": "前回調査: 候補チケットを確認中",
                "summary": "Issue #2 が有力候補",
            },
        ):
            with patch.object(
                supervisor.tool_registry,
                "read_investigate_working_memory_for_case",
                return_value="## Investigate Result\n- 未解決事項: SSO 側ログの追加確認が必要",
            ):
                with patch.object(supervisor.tool_registry, "invoke_tool", side_effect=_invoke_tool):
                    with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
                        evaluate_mock.side_effect = [
                            ObjectiveEvaluatorStructuredResult(
                                criterion_evaluations=[],
                                agent_evaluations=[],
                                overall_summary="plan ok",
                                improvement_points=["調査順序を維持してください"],
                                overall_score=90,
                            ),
                            ObjectiveEvaluatorStructuredResult(
                                criterion_evaluations=[],
                                agent_evaluations=[],
                                overall_summary="result ok",
                                improvement_points=[],
                                overall_score=90,
                            ),
                        ]
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
                                "intake_incident_timeframe": "2025-10-21 20:55 頃",
                                "log_extract_range_start": "2025-10-21T20:40:00",
                                "log_extract_range_end": "2025-10-21T21:10:00",
                                "intake_ticket_context_summary": {
                                    "internal_ticket": "Issue #2: SSO ログイン時に 500 エラーが発生し、再認証で一時回避できます。"
                                },
                            }
                        )

        self.assertEqual(str(result.get("investigation_summary") or ""), "captured:action")
        self.assertEqual(str(result.get("plan_summary") or ""), "captured:plan")
        self.assertEqual(int(result.get("plan_evaluation_score") or 0), 90)
        self.assertEqual(int(result.get("investigation_evaluation_score") or 0), 90)
        self.assertIn("Issue #2 が有力候補", executor.query)
        self.assertIn("認証基盤で再現あり", executor.query)
        self.assertIn("Investigate working memory", executor.query)
        self.assertIn("未解決事項: SSO 側ログの追加確認が必要", executor.query)
        self.assertIn("incident timeframe: 2025-10-21 20:55 頃", executor.query)
        self.assertIn("requested extract range: 2025-10-21T20:40:00 -> 2025-10-21T21:10:00", executor.query)
        self.assertEqual(len(writer.calls), 1)
        written = writer.calls[0]
        self.assertEqual(str(written.get("case_id") or ""), "CASE-TEST-SAMPLE-MEMORY-001")
        self.assertEqual(str(written.get("mode") or ""), "replace")
        self.assertIn("captured", json.dumps(written.get("summary_content"), ensure_ascii=False))
        self.assertIn("Intake category:", json.dumps(written.get("context_content"), ensure_ascii=False))
        self.assertIn("Intake urgency:", json.dumps(written.get("progress_content"), ensure_ascii=False))
        self.assertIn("Judgment rationale:", json.dumps(written.get("summary_content"), ensure_ascii=False))
        self.assertIn("Next action:", json.dumps(written.get("summary_content"), ensure_ascii=False))
        self.assertIn("Adopted sources:", json.dumps(written.get("summary_content"), ensure_ascii=False))

    def test_supervisor_retries_action_when_result_evaluation_is_low(self) -> None:
        executor = _CapturingInvestigateExecutor()
        supervisor = SampleSupervisorAgent(self._build_config(), investigate_executor=executor)

        with patch("support_desk_agent.agents.sample.sample_supervisor_agent.ObjectiveEvaluator.evaluate") as evaluate_mock:
            evaluate_mock.side_effect = [
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="plan ok",
                    improvement_points=["ログ範囲を優先してください"],
                    overall_score=90,
                ),
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="result needs more evidence",
                    improvement_points=["evidence を追加してください"],
                    overall_score=60,
                ),
                ObjectiveEvaluatorStructuredResult(
                    criterion_evaluations=[],
                    agent_evaluations=[],
                    overall_summary="result ok",
                    improvement_points=[],
                    overall_score=90,
                ),
            ]
            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-SAMPLE-LOOP-001",
                    "workspace_path": "/tmp/sample-case",
                    "raw_issue": "vdp.log の原因を調査してください。",
                }
            )

        self.assertEqual(executor.modes, ["plan", "action", "action"])
        self.assertEqual(int(result.get("investigation_followup_loops") or 0), 1)
        self.assertEqual(int(result.get("investigation_evaluation_score") or 0), 90)
        self.assertIn("Result review score: 60", list(result.get("supervisor_followup_notes") or []))


if __name__ == "__main__":
    unittest.main()