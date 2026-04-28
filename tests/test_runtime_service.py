from __future__ import annotations

import base64
import json
import tempfile
import unittest
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.objective_evaluator import (
    ObjectiveEvaluator,
    ObjectiveEvaluatorStructuredResult,
    StructuredAgentEvaluation,
    StructuredCriterionEvaluation,
)
from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    BACK_SUPPORT_ESCALATION_AGENT,
    BACK_SUPPORT_INQUIRY_WRITER_AGENT,
    DRAFT_WRITER_AGENT,
    INVESTIGATE_AGENT,
    INTAKE_AGENT,
    KNOWLEDGE_RETRIEVER_AGENT,
    LOG_ANALYZER_AGENT,
    OBJECTIVE_EVALUATOR,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
)
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.runtime.production.production_service import ProductionRuntimeContext, ProductionRuntimeService, build_runtime_context
from support_ope_agents.tools.case_memory_manager import CaseMemoryManager
from support_ope_agents.tools.default_search_documents import build_default_search_documents_tool
from support_ope_agents.tools.default_write_draft import build_default_write_draft_tool
from support_ope_agents.tools import ToolConfigurationError
from support_ope_agents.tools.registry import ToolSpec
from support_ope_agents.models.state import CaseState


def _fake_objective_evaluation_result() -> ObjectiveEvaluatorStructuredResult:
    return ObjectiveEvaluatorStructuredResult(
        criterion_evaluations=[
            StructuredCriterionEvaluation(
                title="質問意図への回答妥当性",
                viewpoint="ユーザーの主訴に対して、最終回答が結論と次アクションを返しているか",
                result="回答の方向性は妥当ですが、結論の明示がやや弱いです。",
                score=72,
            ),
            StructuredCriterionEvaluation(
                title="調査根拠と構造化情報",
                viewpoint="ログ解析、採用ナレッジ、調査結果の構造化項目が十分に示されているか",
                result="ナレッジ根拠は示されていますが、調査結果の圧縮が不足しています。",
                score=76,
            ),
            StructuredCriterionEvaluation(
                title="情報伝達とメモリ連携",
                viewpoint="shared memory と working memory の間で必要情報が維持されているか",
                result="重要情報の大半は引き継がれていますが、一部の要約は shared memory 側が薄いです。",
                score=68,
            ),
            StructuredCriterionEvaluation(
                title="レビューと最終判断の整合性",
                viewpoint="レビュー結果と最終判断のあいだに矛盾がないか",
                result="最終判断との整合は取れています。",
                score=81,
            ),
        ],
        agent_evaluations=[
            StructuredAgentEvaluation(agent_name="IntakeAgent", score=84, comment="分類と緊急度の整理はできています。"),
            StructuredAgentEvaluation(agent_name="InvestigateAgent", score=78, comment="採用ナレッジと回答ドラフトはありますが、結論の先出しをさらに強められます。"),
        ],
        overall_summary="自動実行は完了していますが、回答の結論提示と memory 連携の明示には改善余地があります。",
        improvement_points=[
            "shared summary に結論と根拠を 1 段落で残してください。",
            "draft_response の冒頭に結論を先出ししてください。",
        ],
        overall_score=75,
    )


def _messages_text(messages: object) -> str:
    if not isinstance(messages, list):
        return str(messages)
    return "\n".join(str(getattr(item, "content", item)) for item in messages)


class _FakeClassifierModel:
    async def ainvoke(self, messages):
        text = _messages_text(messages).lower()
        category = "ambiguous_case"
        urgency = "medium"
        focus = "問い合わせ内容の事実関係と再現条件を確認する"
        if any(token in text for token in ["error", "障害", "gateway", "timeout", "fail", "exception"]):
            category = "incident_investigation"
            focus = "エラー条件と影響範囲を切り分ける"
        elif any(token in text for token in ["機能", "一覧", "アーキテクチャ", "仕様", "使い方"]):
            category = "specification_inquiry"
            focus = "期待動作と現行仕様の差分を確認する"
        if any(token in text for token in ["urgent", "至急", "緊急", "critical", "本番"]):
            urgency = "high"
        return AIMessage(
            content=json.dumps(
                {
                    "category": category,
                    "urgency": urgency,
                    "investigation_focus": focus,
                    "reason": "mocked llm classification",
                },
                ensure_ascii=False,
            )
        )


class _FakeDraftModel:
    async def ainvoke(self, messages):
        text = _messages_text(messages)
        if "gateway" in text.lower() or "error" in text.lower():
            content = "お問い合わせありがとうございます。\n\n現時点の結論として、障害調査を継続しています。追加のログ確認をお願いします。"
        else:
            content = "お問い合わせありがとうございます。\n\n現時点の結論として、アーキテクチャ概要をご案内します。"
        return AIMessage(content=content)

class _FakeToolRegistry:
    def __init__(self, config: AppConfig):
        self._config = config
        self.pii_mask_calls = 0
        self.external_ticket_calls: list[str] = []
        self.internal_ticket_calls: list[str] = []
        case_memory_manager = CaseMemoryManager(config)
        self._read_shared_memory = case_memory_manager.build_default_read_shared_memory_tool()
        self._write_shared_memory = case_memory_manager.build_default_write_shared_memory_tool()
        self._write_intake_working_memory = case_memory_manager.build_default_write_working_memory_tool(INTAKE_AGENT)
        self._search_documents = build_default_search_documents_tool(config)
        self._write_investigate_working_memory = case_memory_manager.build_default_write_working_memory_tool(INVESTIGATE_AGENT)
        self._write_log_working_memory = case_memory_manager.build_default_write_working_memory_tool(LOG_ANALYZER_AGENT)
        self._write_knowledge_working_memory = case_memory_manager.build_default_write_working_memory_tool(KNOWLEDGE_RETRIEVER_AGENT)
        self._write_back_support_draft = build_default_write_draft_tool(config, "back_support_inquiry_draft")
        self._write_customer_draft = build_default_write_draft_tool(config, "customer_response_draft")

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
                ToolSpec(
                    "write_working_memory",
                    "Write intake working memory",
                    self._write_intake_working_memory,
                    provider="builtin",
                    target="default-working-memory-writer",
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
        if role == INVESTIGATE_AGENT:
            return [
                ToolSpec(
                    "detect_log_format",
                    "Detect log format",
                    self._detect_log_format,
                    provider="builtin",
                    target="test-detect-log-format",
                ),
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
                    "write_shared_memory",
                    "Write shared memory",
                    self._write_shared_memory,
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
                ToolSpec(
                    "write_working_memory",
                    "Write working memory",
                    self._write_investigate_working_memory,
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
                ToolSpec(
                    "write_draft",
                    "Write customer draft",
                    self._write_customer_draft,
                    provider="builtin",
                    target="default-draft-writer",
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
                    "write_shared_memory",
                    "Write shared memory",
                    self._write_shared_memory,
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
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
        if role == DRAFT_WRITER_AGENT:
            return [
                ToolSpec(
                    "write_draft",
                    "Write customer draft",
                    self._write_customer_draft,
                    provider="builtin",
                    target="default-draft-writer",
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
        if role == APPROVAL_AGENT:
            return [
                ToolSpec(
                    "record_approval_decision",
                    "Record approval decision",
                    self._record_approval_decision,
                    provider="builtin",
                    target="test-record-approval-decision",
                )
            ]
        if role == TICKET_UPDATE_AGENT:
            return [
                ToolSpec(
                    "prepare_ticket_update",
                    "Prepare ticket update",
                    self._prepare_ticket_update,
                    provider="builtin",
                    target="test-prepare-ticket-update",
                ),
                ToolSpec(
                    "zendesk_reply",
                    "Update Zendesk ticket",
                    self._zendesk_reply,
                    provider="builtin",
                    target="test-zendesk-reply",
                ),
                ToolSpec(
                    "redmine_update",
                    "Update Redmine ticket",
                    self._redmine_update,
                    provider="builtin",
                    target="test-redmine-update",
                ),
            ]
        return []

    @staticmethod
    def _record_approval_decision(*_: object, **__: object) -> str:
        return "approval decision recorded"

    @staticmethod
    def _prepare_ticket_update(*_: object, **__: object) -> str:
        return "ticket update payload prepared"

    @staticmethod
    def _zendesk_reply(*_: object, **__: object) -> str:
        return "zendesk updated"

    @staticmethod
    def _redmine_update(*_: object, **__: object) -> str:
        return "redmine updated"

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
            AgentDefinition(OBJECTIVE_EVALUATOR, ""),
            AgentDefinition(INTAKE_AGENT, ""),
            AgentDefinition(LOG_ANALYZER_AGENT, ""),
            AgentDefinition(KNOWLEDGE_RETRIEVER_AGENT, ""),
            AgentDefinition(DRAFT_WRITER_AGENT, ""),
            AgentDefinition(BACK_SUPPORT_ESCALATION_AGENT, ""),
            AgentDefinition(BACK_SUPPORT_INQUIRY_WRITER_AGENT, ""),
        ]


@dataclass(slots=True)
class _FakeRuntimeContext:
    config: AppConfig
    memory_store: CaseMemoryStore
    runtime_harness_manager: RuntimeHarnessManager
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
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        self._classify_model_patcher = patch(
            "support_ope_agents.tools.default_classify_ticket.build_chat_openai_model",
            return_value=_FakeClassifierModel(),
        )
        # Removed compliance model patcher as it is not needed
        self._classify_model_patcher.start()
        self._objective_eval_patcher = patch.object(
            ObjectiveEvaluator,
            "_invoke_structured_evaluation",
            return_value=_fake_objective_evaluation_result(),
        )
        self._objective_eval_patcher.start()
        self.service = self._build_service(self.config)

    def _build_service(self, config: AppConfig) -> ProductionRuntimeService:
        memory_store = CaseMemoryStore(config)
        runtime_harness_manager = RuntimeHarnessManager(config)
        context = _FakeRuntimeContext(
            config=config,
            memory_store=memory_store,
            runtime_harness_manager=runtime_harness_manager,
            instruction_loader=InstructionLoader(config, memory_store, runtime_harness_manager),
            tool_registry=_FakeToolRegistry(config),
            agent_factory=_FakeAgentFactory(),
            case_id_resolver_service=CaseIdResolverService(),
        )
        return ProductionRuntimeService(context)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self._classify_model_patcher.stop()
        self._objective_eval_patcher.stop()
        self._tmpdir.cleanup()

    def test_instruction_loader_skips_prompts_in_runtime_only_mode(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "DraftWriterAgent": {
                        "constraint_mode": "runtime_only",
                    }
                },
            }
        )
        memory_store = CaseMemoryStore(config)
        loader = InstructionLoader(config, memory_store)

        prompt = loader.load("CASE-TEST", DRAFT_WRITER_AGENT, constraint_mode=config.agents.DraftWriterAgent.constraint_mode)

        self.assertEqual(prompt, "")

    def test_build_runtime_context_validates_enabled_ticket_sources_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_ope_agents:",
                        "  llm:",
                        "    provider: openai",
                        "    model: gpt-4.1",
                        "    api_key: sk-test-value",
                        "  tools:",
                        "    mcp_manifest_path: ./mcp.json",
                        "    ticket_sources:",
                        "      external:",
                        "        enabled: true",
                        "        server: github",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            class _FakeMcpClient:
                def __init__(self) -> None:
                    self.calls: list[str] = []

                def validate_ticket_source(self, *, ticket_kind: str, server_name: str) -> None:
                    self.calls.append(f"{ticket_kind}:{server_name}")

                def validate_logical_tool(self, *, logical_tool_name: str, binding) -> None:
                    return None

            fake_client = _FakeMcpClient()

            with patch(
                "support_ope_agents.runtime.production.production_service.McpToolClient.from_config",
                return_value=fake_client,
            ):
                build_runtime_context(str(config_path))

        self.assertEqual(fake_client.calls, ["external:github"])

    def test_build_runtime_context_fails_fast_when_ticket_source_startup_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_ope_agents:",
                        "  llm:",
                        "    provider: openai",
                        "    model: gpt-4.1",
                        "    api_key: sk-test-value",
                        "  tools:",
                        "    mcp_manifest_path: ./mcp.json",
                        "    ticket_sources:",
                        "      external:",
                        "        enabled: true",
                        "        server: github",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            class _FailingMcpClient:
                def validate_logical_tool(self, *, logical_tool_name: str, binding) -> None:
                    return None

                def validate_ticket_source(self, *, ticket_kind: str, server_name: str) -> None:
                    raise ToolConfigurationError(
                        f"tools.logical_tools.{ticket_kind}_ticket failed startup MCP connectivity check for server '{server_name}': boom"
                    )

            with patch(
                "support_ope_agents.runtime.production.production_service.McpToolClient.from_config",
                return_value=_FailingMcpClient(),
            ):
                with self.assertRaisesRegex(ToolConfigurationError, "tools.logical_tools.external_ticket"):
                    build_runtime_context(str(config_path))

    def test_runtime_harness_manager_describes_role_capabilities(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "default_constraint_mode": "bypass",
                    "KnowledgeRetrieverAgent": {"constraint_mode": "default"},
                },
            }
        )

        harness = RuntimeHarnessManager(config)

        draft_resolution = harness.describe_role(DRAFT_WRITER_AGENT)
        knowledge_resolution = harness.describe_role(KNOWLEDGE_RETRIEVER_AGENT)

        self.assertEqual(draft_resolution["constraint_mode"], "bypass")
        self.assertFalse(draft_resolution["instruction_enabled"])
        self.assertFalse(draft_resolution["runtime_enabled"])
        self.assertFalse(draft_resolution["summary_constraints_enabled"])
        self.assertTrue(any(str(item.get("policy_id") or "") == "draft.summary_snippet_max_chars" for item in draft_resolution["policies"]))
        self.assertEqual(knowledge_resolution["constraint_mode"], "default")
        self.assertTrue(knowledge_resolution["instruction_enabled"])
        self.assertTrue(knowledge_resolution["runtime_enabled"])
        self.assertTrue(knowledge_resolution["summary_constraints_enabled"])
        self.assertTrue(any(str(item.get("policy_id") or "") == "knowledge.highlight_max_chars" for item in knowledge_resolution["policies"]))

    def test_runtime_harness_manager_mode_helpers_match_role_resolution(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "default_constraint_mode": "instruction_only",
                    "DraftWriterAgent": {"constraint_mode": "runtime_only"},
                    "KnowledgeRetrieverAgent": {"constraint_mode": "bypass"},
                },
            }
        )

        harness = RuntimeHarnessManager(config)

        self.assertTrue(RuntimeHarnessManager.runtime_constraints_enabled_for_mode(harness.resolve(DRAFT_WRITER_AGENT)))
        self.assertFalse(RuntimeHarnessManager.instructions_enabled_for_mode(harness.resolve(DRAFT_WRITER_AGENT)))
        self.assertFalse(RuntimeHarnessManager.summary_constraints_enabled_for_mode(harness.resolve(KNOWLEDGE_RETRIEVER_AGENT)))
        self.assertTrue(RuntimeHarnessManager.instructions_enabled_for_mode(harness.resolve(SUPERVISOR_AGENT)))
        self.assertFalse(RuntimeHarnessManager.runtime_constraints_enabled_for_mode(harness.resolve(SUPERVISOR_AGENT)))

    def test_agent_default_constraint_mode_is_inherited_when_agent_setting_is_omitted(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "default_constraint_mode": "bypass",
                    "DraftWriterAgent": {},
                    "KnowledgeRetrieverAgent": {"constraint_mode": "default"},
                },
            }
        )

        self.assertEqual(config.agents.resolve_constraint_mode("DraftWriterAgent"), "bypass")
        self.assertEqual(config.agents.resolve_constraint_mode("KnowledgeRetrieverAgent"), "default")

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
        self.assertEqual(str(state.get("external_ticket_id") or ""), "")
        self.assertEqual(str(state.get("internal_ticket_id") or ""), "")
        registry = cast(_FakeToolRegistry, self.service.context.tool_registry)
        self.assertEqual(registry.pii_mask_calls, 0)

    def test_action_with_uploaded_evidence_skips_incident_timeframe_followup(self) -> None:
        self.service.initialize_case("CASE-TEST-EVIDENCE", str(self.workspace_path))
        self.service.save_workspace_file(
            case_id="CASE-TEST-EVIDENCE",
            workspace_path=str(self.workspace_path),
            relative_dir=".evidence",
            filename="vdp.log",
            content="ERROR Data source vdpcachedatasource not found\n".encode("utf-8"),
        )

        result = self.service.action(
            prompt="添付したファイルはDenodoのvdp.logです。エラー調査をお願いします",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-EVIDENCE",
        )

        state = cast(CaseState, result["state"])
        self.assertNotEqual(str(state.get("status") or ""), "WAITING_CUSTOMER_INPUT")
        self.assertEqual(cast(list[str], state.get("intake_evidence_files") or []), [".evidence/vdp.log"])
        self.assertFalse(bool(result.get("requires_customer_input")))

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
        self.assertEqual(str(state.get("log_extract_range_start") or ""), "2026-04-10T10:00:00")
        self.assertEqual(str(state.get("log_extract_range_end") or ""), "2026-04-10T10:30:00")
        self.assertEqual(str(state.get("external_ticket_id") or ""), "")
        self.assertEqual(str(state.get("internal_ticket_id") or ""), "")

    def test_resume_customer_input_accepts_unknown_incident_timeframe_without_reasking(self) -> None:
        initial = self.service.action(
            prompt="障害が発生しています。gateway error が出ています。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-002-UNKNOWN",
        )

        initial_state = cast(CaseState, initial["state"])
        self.assertEqual(str(initial_state.get("status") or ""), "WAITING_CUSTOMER_INPUT")

        resumed = self.service.resume_customer_input(
            case_id="CASE-TEST-002-UNKNOWN",
            trace_id=str(initial["trace_id"]),
            workspace_path=str(self.workspace_path),
            additional_input="不明です",
            answer_key="intake_incident_timeframe",
        )

        state = cast(CaseState, resumed["state"])
        self.assertNotEqual(str(state.get("status") or ""), "WAITING_CUSTOMER_INPUT")
        self.assertEqual(str(state.get("intake_incident_timeframe") or ""), "不明です")
        answers = dict(state.get("customer_followup_answers") or {})
        self.assertEqual(answers["intake_incident_timeframe"]["answer"], "不明です")

    def test_resume_customer_input_does_not_overwrite_initial_case_title(self) -> None:
        initial = self.service.action(
            prompt="# 初回問い合わせタイトル\n\n障害が発生しています。gateway error が出ています。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-RESUME-TITLE",
        )

        initial_metadata = self.service.context.memory_store.read_case_metadata(str(self.workspace_path))
        self.assertEqual(str(initial_metadata.get("case_title") or ""), "初回問い合わせタイトル")

        self.service.resume_customer_input(
            case_id="CASE-TEST-RESUME-TITLE",
            trace_id=str(initial["trace_id"]),
            workspace_path=str(self.workspace_path),
            additional_input="追加の確認事項です。",
            answer_key="intake_incident_timeframe",
        )

        resumed_metadata = self.service.context.memory_store.read_case_metadata(str(self.workspace_path))
        self.assertEqual(str(resumed_metadata.get("case_title") or ""), "初回問い合わせタイトル")

    def test_action_uses_ai_platform_poc_as_knowledge_source(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "agents": {"KnowledgeRetrieverAgent": {"document_sources": [{"name": "ai-platform-poc", "description": "生成AI基盤のアーキテクチャ検討資料", "path": "/home/user/source/repos/ai-platform-poc"}]}},
                "interfaces": {},
            }
        )
        service = self._build_service(config)

        with patch(
            "support_ope_agents.tools.default_search_documents._invoke_deepagents_search",
            return_value={
                "ai-platform-poc": {
                    "source_name": "ai-platform-poc",
                    "status": "matched",
                    "summary": "業務適用を見据えた生成AI基盤の PoC リポジトリです。",
                    "matched_paths": ["/knowledge/ai-platform-poc/README.md"],
                    "evidence": ["業務適用を見据えた生成AI基盤の PoC リポジトリです。"],
                    "feature_bullets": [],
                    "raw_content": "",
                }
            },
        ):
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

    def test_action_marks_ticket_lookup_unavailable_when_ticket_ids_are_missing(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-008",
        )

        state = cast(CaseState, result["state"])
        self.assertFalse(bool(state.get("external_ticket_lookup_enabled")))
        self.assertFalse(bool(state.get("internal_ticket_lookup_enabled")))
        self.assertEqual(str(state.get("external_ticket_id") or ""), "")
        self.assertEqual(str(state.get("internal_ticket_id") or ""), "")

        results = cast(list[dict[str, object]], state.get("knowledge_retrieval_results") or [])
        external_result = next(item for item in results if str(item.get("source_name") or "") == "external_ticket")
        internal_result = next(item for item in results if str(item.get("source_name") or "") == "internal_ticket")
        self.assertEqual(str(external_result.get("status") or ""), "unavailable")
        self.assertEqual(str(internal_result.get("status") or ""), "unavailable")

        registry = cast(_FakeToolRegistry, self.service.context.tool_registry)
        self.assertEqual(registry.external_ticket_calls, [])
        self.assertEqual(registry.internal_ticket_calls, [])

    def test_action_applies_pii_mask_only_when_enabled(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "agents": {"IntakeAgent": {"pii_mask": {"enabled": True}}},
                "interfaces": {},
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

    def test_describe_control_catalog_lists_core_controls(self) -> None:
        catalog = self.service.describe_control_catalog()

        summary = cast(dict[str, object], catalog["summary"])
        self.assertGreaterEqual(int(summary["control_point_count"]), 8)

        workflow = cast(dict[str, object], catalog["workflow"])
        edges = cast(list[dict[str, object]], workflow["edges"])
        self.assertTrue(
            any(edge.get("control_point_id") == "workflow.route_after_approval.approved" for edge in edges)
        )
        self.assertTrue(any(str(edge.get("to") or "") == "wait_for_customer_input" for edge in edges))

        agents = cast(list[dict[str, object]], catalog["agents"])
        intake_entry = next(item for item in agents if str(item.get("role") or "") == INTAKE_AGENT)
        intake_tools = cast(list[dict[str, object]], intake_entry["tools"])
        self.assertIn("pii_mask", [str(tool.get("name") or "") for tool in intake_tools])

        instruction_catalog = cast(dict[str, object], catalog["instructions"])
        role_entries = cast(list[dict[str, object]], instruction_catalog["roles"])
        supervisor_entry = next(item for item in role_entries if str(item.get("role") or "") == SUPERVISOR_AGENT)
        self.assertTrue(bool(supervisor_entry.get("default_exists")))

    def test_describe_control_catalog_detects_instruction_overrides(self) -> None:
        override_dir = self.workspace_path / "instruction-overrides"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "common.md").write_text("# common override\n", encoding="utf-8")
        (override_dir / f"{INTAKE_AGENT}.md").write_text("# intake override\n", encoding="utf-8")

        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {"instructions_path": str(override_dir)},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        service = self._build_service(config)

        catalog = service.describe_control_catalog()
        instruction_catalog = cast(dict[str, object], catalog["instructions"])
        common_entry = cast(dict[str, object], instruction_catalog["common"])
        self.assertTrue(bool(common_entry.get("override_exists")))

        role_entries = cast(list[dict[str, object]], instruction_catalog["roles"])
        intake_entry = next(item for item in role_entries if str(item.get("role") or "") == INTAKE_AGENT)
        self.assertTrue(bool(intake_entry.get("override_exists")))
        resolved_sources = cast(list[str], intake_entry["resolved_sources"])
        self.assertIn(str(override_dir / "common.md"), resolved_sources)
        self.assertIn(str(override_dir / f"{INTAKE_AGENT}.md"), resolved_sources)

    def test_describe_runtime_audit_reflects_trace_decisions(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-RUNTIME-AUDIT",
        )

        audit = self.service.describe_runtime_audit(
            case_id="CASE-TEST-RUNTIME-AUDIT",
            trace_id=str(result["trace_id"]),
            workspace_path=str(self.workspace_path),
        )

        summary = cast(dict[str, object], audit["summary"])
        self.assertEqual(str(summary["status"]), "WAITING_APPROVAL")
        self.assertEqual(str(summary["workflow_kind"]), "specification_inquiry")

        used_roles = cast(list[str], audit["used_roles"])
        self.assertIn(INVESTIGATE_AGENT, used_roles)

        decision_log = cast(list[dict[str, object]], audit["decision_log"])
        self.assertTrue(any(str(item.get("control_point_id") or "") == "workflow.route_after_investigation.draft_review" for item in decision_log))

    def test_describe_runtime_audit_hides_instruction_resolution_for_default_bypass(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "default_constraint_mode": "bypass",
                    "InvestigateAgent": {"constraint_mode": "default"},
                },
            }
        )
        service = self._build_service(config)

        result = service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-RUNTIME-AUDIT-BYPASS",
        )

        audit = service.describe_runtime_audit(
            case_id="CASE-TEST-RUNTIME-AUDIT-BYPASS",
            trace_id=str(result["trace_id"]),
            workspace_path=str(self.workspace_path),
        )

        entries = cast(list[dict[str, object]], audit["instruction_resolution"])
        runtime_constraints = cast(list[dict[str, object]], audit["runtime_constraints"])
        runtime_policies = cast(dict[str, object], audit["runtime_policies"])
        runtime_policy_effects = cast(list[dict[str, object]], audit["runtime_policy_effects"])
        investigate_entry = next(item for item in entries if str(item.get("role") or "") == INVESTIGATE_AGENT)
        investigate_constraint = next(item for item in runtime_constraints if str(item.get("role") or "") == INVESTIGATE_AGENT)

        self.assertEqual(str(investigate_entry.get("constraint_mode") or ""), "default")
        self.assertTrue(bool(cast(list[str], investigate_entry.get("resolved_sources") or [])))
        self.assertTrue(bool(str(investigate_entry.get("instruction_excerpt") or "")))
        self.assertTrue(bool(investigate_constraint.get("instruction_enabled")))
        self.assertTrue(bool(investigate_constraint.get("runtime_enabled")))
        role_policies = cast(list[dict[str, object]], runtime_policies["role_policies"])
        investigate_policies = next(item for item in role_policies if str(item.get("role") or "") == INVESTIGATE_AGENT)
        investigate_impacts = [
            item for item in runtime_policy_effects if str(item.get("owner") or "") == INVESTIGATE_AGENT
        ]
        self.assertTrue(any(str(item.get("policy_id") or "") == "knowledge.highlight_max_chars" for item in cast(list[dict[str, object]], investigate_policies["policies"])))
        self.assertTrue(any(str(item.get("policy_id") or "") == "knowledge.highlight_max_chars" for item in investigate_impacts))

    def test_generate_support_improvement_report_writes_report_folder(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-011",
        )

        report = self.service.generate_support_improvement_report(
            case_id="CASE-TEST-011",
            trace_id=str(result["trace_id"]),
            workspace_path=str(self.workspace_path),
            checklist=["回答に注意文が含まれているか", "ナレッジソースが記録されているか"],
        )

        report_path = Path(str(report["report_path"]))
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent.name, ".report")
        content = report_path.read_text(encoding="utf-8")
        meta_section = content.split("## Meta", 1)[1].split("## 総合評価", 1)[0]
        self.assertIn("# Support Improvement Report: CASE-TEST-011", content)
        self.assertIn("## 制御サマリー", content)
        self.assertIn("## ランタイム制約一覧", content)
        self.assertIn("## ランタイム制約影響評価", content)
        self.assertIn("## チケット情報", content)
        self.assertIn("External ticket ID", content)
        self.assertIn("Internal ticket ID", content)
        self.assertIn("External ticket fetch", content)
        self.assertIn("Internal ticket fetch", content)
        self.assertNotIn("External ticket ID", meta_section)
        self.assertNotIn("Internal ticket ID", meta_section)
        self.assertLess(content.index("## Meta"), content.index("## 総合評価"))
        self.assertLess(content.index("## 総合評価"), content.index("## Evaluator 評価観点一覧"))
        self.assertLess(content.index("## Evaluator 評価観点一覧"), content.index("## エージェント別評価"))
        self.assertLess(content.index("## エージェント別評価"), content.index("## 問い合わせ内容"))
        self.assertLess(content.index("## 調査に使用したログ・成果物"), content.index("## チケット情報"))
        self.assertLess(content.index("## チケット情報"), content.index("## 問合せ対応結果"))
        self.assertIn("### 発火した制御", content)
        self.assertIn("共通 instruction 制約", content)
        self.assertIn("役割別の想定 instruction 制約", content)
        self.assertIn("InvestigateAgent: mode=default, instruction=yes, runtime=yes, summary=yes", content)
        self.assertIn("global.runtime.workspace_preview_max_chars", content)
        self.assertIn("共有メモリを必ず確認し、既に判明している事実と矛盾しないように振る舞ってください。", content)
        self.assertIn("問い合わせが特定製品や特定機能の説明を求めている場合は、その対象に直接対応する根拠ソースを優先してください。", content)
        self.assertNotIn("## 制御一覧", content)
        self.assertNotIn("## ランタイム制約ポリシー一覧", content)
        self.assertNotIn("[defined] workflow.approval_node", content)
        self.assertIn("sequenceDiagram", content)
        self.assertIn("InvestigateAgent", content)
        self.assertIn("ユーザー指定チェックリスト", content)
        self.assertIn("説明: レポート対象のケースを一意に識別するIDです。", content)
        self.assertIn("## 回答内容", content)
        self.assertIn("サポート担当者に返却した、または返却予定の調査回答本文です。", content)
        self.assertNotIn("LogAnalyzerAgent: needs improvement", content)
        self.assertNotIn("Supervisor->>LogAnalyzer: ログ解析を依頼", content)
        self.assertIn("説明: 最終的に確定した対応方針を示します。", content)
        self.assertIn("### 総評", content)
        self.assertIn("ケース全体を通した自動対応品質の総括です。", content)
        self.assertIn("### 要改善点", content)
        self.assertIn("各エージェントや処理全体の課題、改善点を一覧化します。", content)
        self.assertIn("次工程に必要な判断材料を shared memory の context / progress / summary に明示的に残してください。", content)
        self.assertIn("ユーザー指定観点「回答に注意文が含まれているか」を満たしたことが分かる根拠を、回答本文または shared memory に明示的に残してください。", content)
        self.assertIn("### 点数", content)
        self.assertRegex(content, r"\n\d{1,3} / 100\n")
        self.assertIn("ObjectiveEvaluator", content)
        self.assertIn("## Evaluator 評価観点一覧", content)
        self.assertIn("### 質問意図への回答妥当性", content)
        self.assertIn("### shared memory への情報反映", content)
        self.assertIn("### working memory 起因の伝達漏れ", content)
        self.assertIn("### ユーザー指定観点: 回答に注意文が含まれているか", content)
        self.assertIn("### ユーザー指定観点: ナレッジソースが記録されているか", content)
        self.assertIn("- 対応するユーザー指定観点: 回答に注意文が含まれているか", content)
        self.assertIn("- 評価観点: ", content)
        self.assertIn("- 評価結果: ", content)
        self.assertIn("- 点数: ", content)
        self.assertIn("## サブグラフ詳細シーケンス", content)
        self.assertIn("### IntakeAgent サブグラフ", content)
        self.assertIn("### Draft Review ループ", content)
        self.assertIn("## 情報伝達監査", content)
        self.assertIn("Evaluation rubric", content)
        self.assertRegex(content, r"- IntakeAgent: \d{1,3} / 100 - ")
        self.assertIn("## 問合せ対応結果", content)
        self.assertNotIn("## 結果と評価", content)
        self.assertNotIn("## このリポジトリが扱うこと", content)

    def test_generate_support_improvement_report_lists_evidence_files(self) -> None:
        evidence_dir = self.workspace_path / ".evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "vdp.log").write_text("2025-10-21T20:55:12 ERROR sample\n", encoding="utf-8")

        result = self.service.action(
            prompt="このログのフォーマットを教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-011-EVIDENCE",
        )

        report = self.service.generate_support_improvement_report(
            case_id="CASE-TEST-011-EVIDENCE",
            trace_id=str(result["trace_id"]),
            workspace_path=str(self.workspace_path),
        )

        content = Path(str(report["report_path"])).read_text(encoding="utf-8")

        self.assertIn(".evidence/vdp.log", content)

    def test_action_writes_intake_working_memory(self) -> None:
        self.service.action(
            prompt="ai-chat-utilの機能一覧を出して",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-INTAKE-WM",
        )

        working_path = self.workspace_path / ".memory" / "agents" / INTAKE_AGENT / "working.md"
        content = working_path.read_text(encoding="utf-8")

        self.assertIn("## Intake Result", content)
        self.assertIn("Category: specification_inquiry", content)
        self.assertIn("Urgency: high", content)

    def test_report_skips_false_positive_memory_warnings_for_shared_equivalents(self) -> None:
        result = self.service.action(
            prompt="ai-chat-utilの機能一覧を出して",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-REPORT-WARNINGS",
        )

        report = self.service.generate_support_improvement_report(
            case_id="CASE-TEST-REPORT-WARNINGS",
            trace_id=str(result["trace_id"]),
            workspace_path=str(self.workspace_path),
        )

        content = Path(str(report["report_path"])).read_text(encoding="utf-8")
        meta_section = content.split("## Meta", 1)[1].split("## 総合評価", 1)[0]

        self.assertIn("## チケット情報", content)
        self.assertIn("External ticket ID", content)
        self.assertIn("Internal ticket ID", content)
        self.assertIn("External ticket fetch", content)
        self.assertIn("Internal ticket fetch", content)
        self.assertNotIn("External ticket ID", meta_section)
        self.assertNotIn("Internal ticket ID", meta_section)
        self.assertNotIn("Adopted sources: none", content)

    def test_initialize_case_creates_objective_evaluator_working_memory(self) -> None:
        self.service.initialize_case("CASE-TEST-017", str(self.workspace_path))

        working_memory = self.workspace_path / ".memory" / "agents" / OBJECTIVE_EVALUATOR / "working.md"
        self.assertTrue(working_memory.exists())

    def test_objective_evaluator_settings_are_loaded(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "ObjectiveEvaluator": {
                        "pass_score": 85,
                        "missing_shared_memory_penalty": 20,
                    }
                },
            }
        )

        self.assertEqual(config.agents.ObjectiveEvaluator.pass_score, 85)
        self.assertEqual(config.agents.ObjectiveEvaluator.missing_shared_memory_penalty, 20)

    def test_action_does_not_write_legacy_json_state_file(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-013",
        )

        legacy_state_path = self.workspace_path / ".traces" / f"{result['trace_id']}.json"
        self.assertFalse(legacy_state_path.exists())
        self.assertTrue((self.workspace_path / ".traces" / "checkpoints.sqlite").exists())

    def test_checkpoint_status_lists_workspace_scoped_trace_ids(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-014",
        )

        status = self.service.checkpoint_status(
            case_id="CASE-TEST-014",
            workspace_path=str(self.workspace_path),
            trace_id=str(result["trace_id"]),
        )

        self.assertTrue(bool(status.get("exists")))
        self.assertIn(str(result["trace_id"]), cast(list[str], status.get("trace_ids") or []))

    def test_list_cases_includes_message_count(self) -> None:
        first_workspace = self.workspace_path / "CASE-ONE"
        second_workspace = self.workspace_path / "CASE-TWO"
        self.service.initialize_case("CASE-ONE", str(first_workspace))
        self.service.initialize_case("CASE-TWO", str(second_workspace))
        self.service.context.memory_store.update_case_metadata(str(first_workspace), case_title="障害調査: API タイムアウト")
        self.service.context.memory_store.append_chat_history(
            "CASE-ONE",
            str(first_workspace),
            {"role": "user", "content": "hello"},
        )

        cases = self.service.list_cases(str(self.workspace_path))

        case_index = {item["case_id"]: item for item in cases}
        self.assertEqual(case_index["CASE-ONE"]["message_count"], 1)
        self.assertEqual(case_index["CASE-TWO"]["message_count"], 0)
        self.assertEqual(case_index["CASE-ONE"]["case_title"], "障害調査: API タイムアウト")
        self.assertEqual(case_index["CASE-TWO"]["case_title"], "CASE-TWO")

    def test_list_cases_returns_newest_updated_case_first(self) -> None:
        older_workspace = self.workspace_path / "CASE-OLDER"
        newer_workspace = self.workspace_path / "CASE-NEWER"
        self.service.initialize_case("CASE-OLDER", str(older_workspace))
        self.service.initialize_case("CASE-NEWER", str(newer_workspace))

        self.service.context.memory_store.append_chat_history(
            "CASE-OLDER",
            str(older_workspace),
            {"role": "user", "content": "older"},
        )
        self.service.context.memory_store.append_chat_history(
            "CASE-NEWER",
            str(newer_workspace),
            {"role": "user", "content": "newer"},
        )

        import os
        older_time = older_workspace.stat().st_mtime - 60
        newer_time = newer_workspace.stat().st_mtime
        os.utime(older_workspace, (older_time, older_time))
        os.utime(newer_workspace, (newer_time, newer_time))

        cases = self.service.list_cases(str(self.workspace_path))

        self.assertEqual([item["case_id"] for item in cases[:2]], ["CASE-NEWER", "CASE-OLDER"])

    def test_list_cases_prefers_metadata_updated_at_over_directory_mtime(self) -> None:
        older_workspace = self.workspace_path / "CASE-META-OLDER"
        newer_workspace = self.workspace_path / "CASE-META-NEWER"
        self.service.initialize_case("CASE-META-OLDER", str(older_workspace))
        self.service.initialize_case("CASE-META-NEWER", str(newer_workspace))

        self.service.context.memory_store.touch_case(str(older_workspace), updated_at="2026-04-16T09:00:00+00:00")
        self.service.context.memory_store.touch_case(str(newer_workspace), updated_at="2026-04-18T10:30:00+00:00")

        import os
        base_time = older_workspace.stat().st_mtime
        os.utime(older_workspace, (base_time + 300, base_time + 300))
        os.utime(newer_workspace, (base_time - 300, base_time - 300))

        cases = self.service.list_cases(str(self.workspace_path))

        self.assertEqual([item["case_id"] for item in cases[:2]], ["CASE-META-NEWER", "CASE-META-OLDER"])
        self.assertEqual(cases[0]["updated_at"], "2026-04-18T10:30:00+00:00")

    def test_action_persists_case_title_for_case_list(self) -> None:
        case_workspace = self.workspace_path / "CASE-TEST-TITLE"
        self.service.action(
            prompt="# API 連携後に circular import で収集失敗する件\n\n詳細を確認してください。",
            workspace_path=str(case_workspace),
            case_id="CASE-TEST-TITLE",
        )

        cases = self.service.list_cases(str(self.workspace_path))
        case_index = {item["case_id"]: item for item in cases}

        self.assertEqual(case_index["CASE-TEST-TITLE"]["case_title"], "API 連携後に circular import で収集失敗する件")

    def test_list_cases_backfills_missing_case_title_from_first_user_message(self) -> None:
        workspace = self.workspace_path / "CASE-LEGACY"
        self.service.initialize_case("CASE-LEGACY", str(workspace))
        self.service.context.memory_store.append_chat_history(
            "CASE-LEGACY",
            str(workspace),
            {"role": "user", "content": "# 古いケースの問い合わせタイトル\n\n詳細本文"},
        )

        cases = self.service.list_cases(str(self.workspace_path))
        case_index = {item["case_id"]: item for item in cases}

        self.assertEqual(case_index["CASE-LEGACY"]["case_title"], "古いケースの問い合わせタイトル")
        metadata = self.service.context.memory_store.read_case_metadata(str(workspace))
        self.assertEqual(str(metadata.get("case_title") or ""), "古いケースの問い合わせタイトル")

    def test_list_cases_reads_workspace_root_only(self) -> None:
        direct_workspace = self.workspace_path / "CASE-DIRECT"
        legacy_root = self.workspace_path / "cases"
        legacy_workspace = legacy_root / "CASE-LEGACY-SUBDIR"
        self.service.initialize_case("CASE-DIRECT", str(direct_workspace))
        self.service.initialize_case("CASE-LEGACY-SUBDIR", str(legacy_workspace))

        cases = self.service.list_cases(str(self.workspace_path))

        case_ids = {str(item["case_id"]) for item in cases}
        self.assertIn("CASE-DIRECT", case_ids)
        self.assertNotIn("CASE-LEGACY-SUBDIR", case_ids)

    def test_workspace_roundtrip_and_archive(self) -> None:
        self.service.initialize_case("CASE-TEST-015", str(self.workspace_path))

        uploaded = self.service.save_workspace_file(
            case_id="CASE-TEST-015",
            workspace_path=str(self.workspace_path),
            relative_dir="uploads",
            filename="sample.txt",
            content="workspace payload".encode("utf-8"),
        )
        listing = self.service.list_workspace_entries(
            case_id="CASE-TEST-015",
            workspace_path=str(self.workspace_path),
            relative_path="uploads",
        )
        preview = self.service.get_workspace_file(
            case_id="CASE-TEST-015",
            workspace_path=str(self.workspace_path),
            relative_path="uploads/sample.txt",
            max_chars=32,
        )
        archive_path = self.service.create_workspace_archive(
            case_id="CASE-TEST-015",
            workspace_path=str(self.workspace_path),
        )

        self.assertEqual(uploaded["path"], "uploads/sample.txt")
        self.assertEqual(listing["entries"][0]["name"], "sample.txt")
        self.assertEqual(preview["content"], "workspace payload")
        self.assertTrue(archive_path.exists())
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn(f"{self.workspace_path.name}/uploads/sample.txt", archive.namelist())

    def test_action_appends_chat_history_messages(self) -> None:
        result = self.service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-016",
        )

        history = self.service.get_chat_history(case_id="CASE-TEST-016", workspace_path=str(self.workspace_path))

        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["event"], "action")
        self.assertEqual(history[0]["content"], "生成AI基盤のアーキテクチャ概要を教えてください。")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["trace_id"], result["trace_id"])

    def test_action_merges_generic_followup_with_previous_issue(self) -> None:
        self.service.action(
            prompt="ai-chat-utilについて教えて",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-017-FOLLOWUP",
        )

        result = self.service.action(
            prompt="詳細を教えてください",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-017-FOLLOWUP",
        )

        state = cast(CaseState, result["state"])
        raw_issue = str(state.get("raw_issue") or "")
        self.assertIn("ai-chat-utilについて教えて", raw_issue)
        self.assertIn("[Follow-up request]", raw_issue)
        self.assertIn("詳細を教えてください", raw_issue)

    def test_action_merges_generic_followup_with_request_conversation_messages(self) -> None:
        result = self.service.action(
            prompt="詳細を教えてください",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-018-FOLLOWUP",
            conversation_messages=[
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
        )

        state = cast(CaseState, result["state"])
        raw_issue = str(state.get("raw_issue") or "")
        self.assertIn("ai-chat-utilについて教えて", raw_issue)
        self.assertIn("[Follow-up request]", raw_issue)
        self.assertIn("詳細を教えてください", raw_issue)

    def test_action_stores_langchain_conversation_messages_in_state(self) -> None:
        result = self.service.action(
            prompt="詳細を教えてください",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-019-CONVERSATION",
            conversation_messages=[
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
        )

        state = cast(CaseState, result["state"])
        raw_issue = str(state.get("raw_issue") or "")
        conversation_messages = cast(list[dict[str, object]], state.get("conversation_messages") or [])
        self.assertIn("ai-chat-utilについて教えて", raw_issue)
        self.assertIn("詳細を教えてください", raw_issue)
        self.assertEqual(str(conversation_messages[0].get("type") or ""), "human")
        self.assertEqual(str(cast(dict[str, object], conversation_messages[-1].get("data") or {}).get("content") or ""), "詳細を教えてください")

    def test_action_auto_generates_report_when_supervisor_enabled(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "SuperVisorAgent": {"auto_generate_report": True, "report_on": ["waiting_approval"]}
                },
            }
        )
        service = self._build_service(config)

        result = service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-015",
        )

        report_path = Path(str(result.get("report_path") or ""))
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent.name, ".report")

    def test_action_does_not_auto_generate_report_for_non_matching_trigger(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "SuperVisorAgent": {"auto_generate_report": True, "report_on": ["closed"]}
                },
            }
        )
        service = self._build_service(config)

        result = service.action(
            prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
            workspace_path=str(self.workspace_path),
            case_id="CASE-TEST-016",
        )

        self.assertIsNone(result.get("report_path"))

    def test_supervisor_report_on_accepts_single_string(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "SuperVisorAgent": {"auto_generate_report": True, "report_on": "waiting_approval"}
                },
            }
        )
        self.assertEqual(config.agents.SuperVisorAgent.report_on, ["waiting_approval"])

    def test_supervisor_max_investigation_loops_is_passed_to_executor(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "SuperVisorAgent": {"max_investigation_loops": 2}
                },
            }
        )

        service = self._build_service(config)

        self.assertEqual(service._supervisor_executor.max_investigation_loops, 2)

    def test_action_auto_generates_report_for_closed_trigger(self) -> None:
        captured: dict[str, object] = {}

        class _FakeWorkflow:
            def invoke(self, state: CaseState, config: dict[str, object] | None = None) -> CaseState:
                updated = dict(state)
                updated["status"] = "CLOSED"
                updated["ticket_update_result"] = "updated"
                return cast(CaseState, updated)

        def _fake_build_case_workflow(*, checkpointer=None, intake_executor=None, approval_executor=None, ticket_update_executor=None, supervisor_executor=None):
            captured["checkpointer"] = checkpointer
            return _FakeWorkflow()

        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {
                    "SuperVisorAgent": {"auto_generate_report": True, "report_on": ["closed"]}
                },
            }
        )
        service = self._build_service(config)

        with patch.object(
            ProductionRuntimeService,
            "_build_case_workflow",
            autospec=True,
            side_effect=lambda self, *, checkpointer=None: _fake_build_case_workflow(checkpointer=checkpointer),
        ):
            result = service.action(
                prompt="クローズまで進むケースです。",
                workspace_path=str(self.workspace_path),
                case_id="CASE-TEST-017",
            )

        report_path = Path(str(result.get("report_path") or ""))
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent.name, ".report")

    def test_action_uses_workspace_scoped_sqlite_checkpointer_when_available(self) -> None:
        captured: dict[str, object] = {}

        class _FakeCheckpointer:
            def __init__(self, conn_string: str):
                self.conn_string = conn_string

        class _FakeSqliteSaver:
            @staticmethod
            def from_conn_string(conn_string: str):
                captured["conn_string"] = conn_string

                class _ContextManager:
                    def __enter__(self):
                        return _FakeCheckpointer(conn_string)

                    def __exit__(self, exc_type, exc, tb):
                        return False

                return _ContextManager()

        class _FakeWorkflow:
            def invoke(self, state: CaseState, config: dict[str, object] | None = None) -> CaseState:
                captured["invoke_config"] = config or {}
                updated = dict(state)
                updated["status"] = "WAITING_APPROVAL"
                return cast(CaseState, updated)

        def _fake_build_case_workflow(*, checkpointer=None, intake_executor=None, approval_executor=None, ticket_update_executor=None, supervisor_executor=None):
            captured["checkpointer"] = checkpointer
            return _FakeWorkflow()

        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {"checkpoint_db_filename": "workflow.sqlite"},
                "interfaces": {},
                "agents": {},
            }
        )
        service = self._build_service(config)

        with patch("support_ope_agents.runtime.abstract_service.SqliteSaver", _FakeSqliteSaver), patch.object(
            ProductionRuntimeService,
            "_build_case_workflow",
            autospec=True,
            side_effect=lambda self, *, checkpointer=None: _fake_build_case_workflow(checkpointer=checkpointer),
        ):
            result = service.action(
                prompt="生成AI基盤のアーキテクチャ概要を教えてください。",
                workspace_path=str(self.workspace_path),
                case_id="CASE-TEST-012",
            )

        self.assertEqual(str(captured.get("conn_string") or ""), str(self.workspace_path / ".traces" / "workflow.sqlite"))
        self.assertIsNotNone(captured.get("checkpointer"))
        self.assertEqual(
            captured.get("invoke_config"),
            {"configurable": {"thread_id": str(result["trace_id"]), "checkpoint_ns": ""}},
        )


if __name__ == "__main__":
    unittest.main()