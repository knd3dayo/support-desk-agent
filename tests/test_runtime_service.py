from __future__ import annotations

import base64
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import (
    BACK_SUPPORT_ESCALATION_AGENT,
    BACK_SUPPORT_INQUIRY_WRITER_AGENT,
    INTAKE_AGENT,
    KNOWLEDGE_RETRIEVER_AGENT,
    LOG_ANALYZER_AGENT,
    SUPERVISOR_AGENT,
)
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.runtime.service import RuntimeContext, RuntimeService
from support_ope_agents.tools.default_read_shared_memory import build_default_read_shared_memory_tool
from support_ope_agents.tools.default_search_documents import build_default_search_documents_tool
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool
from support_ope_agents.tools.default_write_shared_memory import build_default_write_shared_memory_tool
from support_ope_agents.tools.default_write_working_memory import build_default_write_working_memory_tool
from support_ope_agents.tools.registry import ToolSpec
from support_ope_agents.workflow.state import CaseState


class _FakeToolRegistry:
    def __init__(self, config: AppConfig):
        self._config = config
        self.pii_mask_calls = 0
        self.external_ticket_calls: list[str] = []
        self.internal_ticket_calls: list[str] = []
        self._read_shared_memory = build_default_read_shared_memory_tool(config)
        self._write_shared_memory = build_default_write_shared_memory_tool(config)
        self._search_documents = build_default_search_documents_tool(config)
        self._write_log_working_memory = build_default_write_working_memory_tool(config, LOG_ANALYZER_AGENT)
        self._write_knowledge_working_memory = build_default_write_working_memory_tool(config, KNOWLEDGE_RETRIEVER_AGENT)
        self._write_back_support_draft = build_default_write_draft_tool(config, "back_support_inquiry_draft")

    def get_tools(self, role: str) -> list[ToolSpec]:
        if role == INTAKE_AGENT:
            return [
                ToolSpec("pii_mask", "Mask secrets", self._pii_mask, provider="builtin", target="test-pii-mask"),
                ToolSpec("external_ticket", "External ticket", self._external_ticket, provider="builtin", target="test-external-ticket"),
                ToolSpec("internal_ticket", "Internal ticket", self._internal_ticket, provider="builtin", target="test-internal-ticket"),
                ToolSpec(
                    "classify_ticket",
                    "Classify ticket",
                    self._classify_ticket,
                    provider="builtin",
                    target="test-classify-ticket",
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared memory",
                    self._write_shared_memory,
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
            ]
        if role == LOG_ANALYZER_AGENT:
            return [
                ToolSpec(
                    "detect_log_format",
                    "Detect log format",
                    self._detect_log_format,
                    provider="builtin",
                    target="test-detect-log-format",
                ),
                ToolSpec(
                    "write_working_memory",
                    "Write working memory",
                    self._write_log_working_memory,
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
            ]
        if role == KNOWLEDGE_RETRIEVER_AGENT:
            return [
                ToolSpec(
                    "search_documents",
                    "Search documents",
                    self._search_documents,
                    provider="builtin",
                    target="configured-document-sources",
                ),
                ToolSpec("external_ticket", "External ticket", self._external_ticket, provider="builtin", target="test-external-ticket"),
                ToolSpec("internal_ticket", "Internal ticket", self._internal_ticket, provider="builtin", target="test-internal-ticket"),
                ToolSpec(
                    "write_working_memory",
                    "Write working memory",
                    self._write_knowledge_working_memory,
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
            ]
        if role == BACK_SUPPORT_ESCALATION_AGENT:
            return [
                ToolSpec(
                    "read_shared_memory",
                    "Read shared memory",
                    self._read_shared_memory,
                    provider="builtin",
                    target="default-case-memory-reader",
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared memory",
                    self._write_shared_memory,
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
            ]
        if role == BACK_SUPPORT_INQUIRY_WRITER_AGENT:
            return [
                ToolSpec(
                    "write_draft",
                    "Write draft",
                    self._write_back_support_draft,
                    provider="builtin",
                    target="default-draft-writer",
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared memory",
                    self._write_shared_memory,
                    provider="builtin",
                    target="default-case-memory-writer",
                )
            ]
        if role == SUPERVISOR_AGENT:
            return [
                ToolSpec(
                    "read_shared_memory",
                    "Read shared memory",
                    self._read_shared_memory,
                    provider="builtin",
                    target="default-case-memory-reader",
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared memory",
                    self._write_shared_memory,
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
            ]
        return []

    def _pii_mask(self, text: str, _: str) -> str:
        self.pii_mask_calls += 1
        return f"[MASKED]{text}"

    @staticmethod
    def _classify_ticket(text: str, _: str) -> str:
        category = "incident_investigation" if "障害" in text or "error" in text.lower() else "specification_inquiry"
        return json.dumps(
            {
                "category": category,
                "urgency": "high",
                "investigation_focus": "一次切り分けと原因候補の確認",
                "reason": "テスト用スタブ分類",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _detect_log_format(log_file_path: str, _terms: list[str]) -> str:
        return json.dumps(
            {
                "detected_format": "plain",
                "has_java_stacktrace": False,
                "generated_patterns": {},
                "search_results": {"severity": ["ERROR"], "java_exception": []},
                "selected_file": log_file_path,
            },
            ensure_ascii=False,
        )

    def _external_ticket(self, *_: object, **kwargs: object) -> str:
        ticket_id = str(kwargs.get("ticket_id") or "")
        if ticket_id:
            self.external_ticket_calls.append(ticket_id)
            return json.dumps(
                {
                    "ticket_id": ticket_id,
                    "summary": f"external ticket fetched: {ticket_id}",
                    "attachments": [
                        {
                            "filename": "external-context.txt",
                            "content": f"External ticket context for {ticket_id}",
                        },
                        {
                            "filename": "external-log.log",
                            "content_base64": base64.b64encode(
                                b"2026-04-10 10:15 ERROR external ticket attached log\n"
                            ).decode("ascii"),
                        },
                    ],
                },
                ensure_ascii=False,
            )
        return "external_ticket tool is not configured."

    def _internal_ticket(self, *_: object, **kwargs: object) -> str:
        ticket_id = str(kwargs.get("ticket_id") or "")
        if ticket_id:
            self.internal_ticket_calls.append(ticket_id)
            return json.dumps(
                {
                    "ticket_id": ticket_id,
                    "summary": f"internal ticket fetched: {ticket_id}",
                    "attachments": [
                        {
                            "filename": "internal-context.txt",
                            "content": f"Internal ticket context for {ticket_id}",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        return "internal_ticket tool is not configured."


class _FakeAgentFactory:
    @staticmethod
    def build_default_definitions() -> list[AgentDefinition]:
        return [
            AgentDefinition(SUPERVISOR_AGENT, ""),
            AgentDefinition(INTAKE_AGENT, ""),
            AgentDefinition(LOG_ANALYZER_AGENT, ""),
            AgentDefinition(KNOWLEDGE_RETRIEVER_AGENT, ""),
            AgentDefinition(BACK_SUPPORT_ESCALATION_AGENT, ""),
            AgentDefinition(BACK_SUPPORT_INQUIRY_WRITER_AGENT, ""),
        ]


@dataclass(slots=True)
class _FakeRuntimeContext:
    config: AppConfig
    memory_store: CaseMemoryStore
    instruction_loader: InstructionLoader
    tool_registry: _FakeToolRegistry
    agent_factory: _FakeAgentFactory
    case_id_resolver_service: CaseIdResolverService


class RuntimeServiceFlowTests(unittest.TestCase):
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
        self.service = self._build_service(self.config)

    def _build_service(self, config: AppConfig) -> RuntimeService:
        memory_store = CaseMemoryStore(config)
        context = _FakeRuntimeContext(
            config=config,
            memory_store=memory_store,
            instruction_loader=InstructionLoader(config, memory_store),
            tool_registry=_FakeToolRegistry(config),
            agent_factory=_FakeAgentFactory(),
            case_id_resolver_service=CaseIdResolverService(),
        )
        return RuntimeService(context)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_action_sets_log_analysis_fields_and_waits_for_approval(self) -> None:
        evidence_dir = self.workspace_path / ".evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        log_file = evidence_dir / "application.log"
        log_file.write_text("2026-04-10 10:15 ERROR gateway timeout\n", encoding="utf-8")

        result = self.service.action(
            prompt="2026-04-10 10:15 に障害が発生し、gateway error が出ています。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-001",
        )

        state = cast(CaseState, result["state"])
        self.assertEqual(str(state.get("status") or ""), "WAITING_APPROVAL")
        self.assertIn("application.log を解析", str(state.get("log_analysis_summary") or ""))
        self.assertEqual(str(state.get("log_analysis_file") or ""), str(log_file.resolve()))
        self.assertEqual(str(state.get("external_ticket_id") or ""), str(result.get("external_ticket_id") or ""))
        self.assertEqual(str(state.get("internal_ticket_id") or ""), str(result.get("internal_ticket_id") or ""))
        self.assertTrue(str(state.get("external_ticket_id") or "").startswith("EXT-TRACE-"))
        self.assertTrue(str(state.get("internal_ticket_id") or "").startswith("INT-TRACE-"))
        registry = cast(_FakeToolRegistry, self.service.context.tool_registry)
        self.assertEqual(registry.pii_mask_calls, 0)

    def test_resume_customer_input_stores_answer_and_reaches_waiting_approval(self) -> None:
        initial = self.service.action(
            prompt="障害が発生しています。gateway error が出ています。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-002",
        )

        initial_state = cast(CaseState, initial["state"])
        self.assertEqual(str(initial_state.get("status") or ""), "WAITING_CUSTOMER_INPUT")
        self.assertIn("intake_incident_timeframe", dict(initial_state.get("intake_followup_questions") or {}))

        resumed = self.service.resume_customer_input(
            case_id="CASE-TEST-002",
            trace_id=str(initial["trace_id"]),
            workspace_path=str(self.workspace_path),
            additional_input="2026-04-10 10:15 頃に初回発生しました。",
            answer_key="intake_incident_timeframe",
        )

        state = cast(CaseState, resumed["state"])
        self.assertEqual(str(state.get("status") or ""), "WAITING_APPROVAL")
        self.assertTrue(resumed["requires_approval"])
        answers = dict(state.get("customer_followup_answers") or {})
        self.assertIn("intake_incident_timeframe", answers)
        self.assertEqual(
            answers["intake_incident_timeframe"]["answer"],
            "2026-04-10 10:15 頃に初回発生しました。",
        )
        self.assertTrue(str(state.get("external_ticket_id") or "").startswith("EXT-TRACE-"))
        self.assertTrue(str(state.get("internal_ticket_id") or "").startswith("INT-TRACE-"))

    def test_action_uses_ai_platform_poc_as_knowledge_source(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "knowledge_retrieval": {
                    "document_sources": [
                        {
                            "name": "ai-platform-poc",
                            "description": "生成AI基盤のアーキテクチャ検討資料",
                            "path": "/home/user/source/repos/ai-platform-poc",
                        }
                    ]
                },
                "interfaces": {},
                "agents": {},
            }
        )
        service = self._build_service(config)

        result = service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-006",
        )

        state = cast(CaseState, result["state"])
        self.assertEqual(str(state.get("status") or ""), "WAITING_APPROVAL")
        self.assertIn("ai-platform-poc", str(state.get("knowledge_retrieval_summary") or ""))
        self.assertEqual(str(state.get("knowledge_retrieval_final_adopted_source") or ""), "ai-platform-poc")

    def test_action_respects_explicit_ticket_ids(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤の内部外部チケットを参照してください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-007",
            external_ticket_id="ext-123",
            internal_ticket_id="int-456",
        )

        state = cast(CaseState, result["state"])
        self.assertEqual(str(state.get("external_ticket_id") or ""), "EXT-123")
        self.assertEqual(str(state.get("internal_ticket_id") or ""), "INT-456")
        self.assertTrue(bool(state.get("external_ticket_lookup_enabled")))
        self.assertTrue(bool(state.get("internal_ticket_lookup_enabled")))
        ticket_context = cast(dict[str, str], state.get("intake_ticket_context_summary") or {})
        ticket_artifacts = cast(dict[str, list[str]], state.get("intake_ticket_artifacts") or {})
        self.assertIn("external_ticket", ticket_context)
        self.assertIn("internal_ticket", ticket_context)
        self.assertTrue(ticket_artifacts.get("external_ticket"))
        self.assertTrue(ticket_artifacts.get("internal_ticket"))
        for path in ticket_artifacts["external_ticket"] + ticket_artifacts["internal_ticket"]:
            self.assertTrue(Path(path).exists())
        registry = cast(_FakeToolRegistry, self.service.context.tool_registry)
        self.assertEqual(registry.external_ticket_calls, ["EXT-123"])
        self.assertEqual(registry.internal_ticket_calls, ["INT-456"])

        results = cast(list[dict[str, object]], state.get("knowledge_retrieval_results") or [])
        external_result = next(item for item in results if str(item.get("source_name") or "") == "external_ticket")
        internal_result = next(item for item in results if str(item.get("source_name") or "") == "internal_ticket")
        self.assertEqual(str(external_result.get("status") or ""), "hydrated")
        self.assertEqual(str(internal_result.get("status") or ""), "hydrated")

    def test_action_skips_ticket_lookup_for_auto_generated_ticket_ids(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-008",
        )

        state = cast(CaseState, result["state"])
        self.assertFalse(bool(state.get("external_ticket_lookup_enabled")))
        self.assertFalse(bool(state.get("internal_ticket_lookup_enabled")))
        self.assertTrue(str(state.get("external_ticket_id") or "").startswith("EXT-TRACE-"))
        self.assertTrue(str(state.get("internal_ticket_id") or "").startswith("INT-TRACE-"))

        results = cast(list[dict[str, object]], state.get("knowledge_retrieval_results") or [])
        external_result = next(item for item in results if str(item.get("source_name") or "") == "external_ticket")
        internal_result = next(item for item in results if str(item.get("source_name") or "") == "internal_ticket")
        self.assertEqual(str(external_result.get("status") or ""), "skipped")
        self.assertEqual(str(internal_result.get("status") or ""), "skipped")

        registry = cast(_FakeToolRegistry, self.service.context.tool_registry)
        self.assertEqual(registry.external_ticket_calls, [])
        self.assertEqual(registry.internal_ticket_calls, [])

    def test_action_applies_pii_mask_only_when_enabled(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "intake": {"pii_mask": {"enabled": True}},
                "interfaces": {},
                "agents": {},
            }
        )
        service = self._build_service(config)

        result = service.action(
            prompt="password=secret の問い合わせです。仕様を確認したいです。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-009",
        )

        state = cast(CaseState, result["state"])
        self.assertTrue(str(state.get("masked_issue") or "").startswith("[MASKED]"))
        registry = cast(_FakeToolRegistry, service.context.tool_registry)
        self.assertEqual(registry.pii_mask_calls, 1)

    def test_action_prioritizes_intake_hydrated_log_attachment(self) -> None:
        evidence_dir = self.workspace_path / ".evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        lower_priority_log = evidence_dir / "application.log"
        lower_priority_log.write_text("2026-04-10 10:15 ERROR workspace log\n", encoding="utf-8")

        result = self.service.action(
            prompt="2026-04-10 10:15 に障害が発生し、external ticket も確認してください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-010",
            external_ticket_id="ext-789",
        )

        state = cast(CaseState, result["state"])
        selected_file = str(state.get("log_analysis_file") or "")
        self.assertIn(".artifacts/intake/external_attachments/external-log.log", selected_file)
        self.assertNotEqual(selected_file, str(lower_priority_log.resolve()))


if __name__ == "__main__":
    unittest.main()