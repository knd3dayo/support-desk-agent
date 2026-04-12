from __future__ import annotations

import mimetypes
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import cast
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver

from support_ope_agents.agents.approval_agent import ApprovalAgent
from support_ope_agents.agents.back_support_escalation_agent import BackSupportEscalationPhaseExecutor
from support_ope_agents.agents.back_support_inquiry_writer_agent import BackSupportInquiryWriterPhaseExecutor
from support_ope_agents.agents.compliance_reviewer_agent import ComplianceReviewerPhaseExecutor
from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
from support_ope_agents.agents.intake_agent import IntakeAgent
from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.agents.ticket_update_agent import TicketUpdateAgent
from support_ope_agents.agents.roles import BACK_SUPPORT_ESCALATION_AGENT
from support_ope_agents.agents.roles import BACK_SUPPORT_INQUIRY_WRITER_AGENT
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT
from support_ope_agents.agents.roles import DRAFT_WRITER_AGENT
from support_ope_agents.agents.roles import APPROVAL_AGENT
from support_ope_agents.agents.roles import INTAKE_AGENT
from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT
from support_ope_agents.agents.roles import LOG_ANALYZER_AGENT
from support_ope_agents.agents.roles import SUPERVISOR_AGENT
from support_ope_agents.agents.roles import TICKET_UPDATE_AGENT
from support_ope_agents.agents.deep_agent_factory import DeepAgentFactory
from support_ope_agents.config import AppConfig, load_config
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.runtime.case_titles import derive_case_title
from support_ope_agents.runtime.conversation_messages import append_serialized_message, coerce_serialized_conversation_messages, deserialize_langchain_messages
from support_ope_agents.runtime.control_catalog import build_control_catalog, build_runtime_audit
from support_ope_agents.runtime.reporting import build_support_improvement_report
from support_ope_agents.runtime.case_id_resolver import CASE_ID_FILENAME
from support_ope_agents.tools import ToolRegistry
from support_ope_agents.tools.builtin_tools import TEXT_FILE_SUFFIXES
from support_ope_agents.tools.default_check_policy import build_default_check_policy_tool
from support_ope_agents.tools.default_request_revision import build_default_request_revision_tool
from support_ope_agents.tools.mcp_overrides import McpToolOverrideResolver
from support_ope_agents.workflow import (
    WORKFLOW_LABELS,
    build_case_workflow,
    build_plan_steps,
    route_workflow,
    summarize_plan,
)
from support_ope_agents.workflow.state import CaseState, WorkflowKind


@dataclass(slots=True)
class RuntimeContext:
    config: AppConfig
    memory_store: CaseMemoryStore
    instruction_loader: InstructionLoader
    tool_registry: ToolRegistry
    agent_factory: DeepAgentFactory
    case_id_resolver_service: CaseIdResolverService


def build_runtime_context(config_path: str) -> RuntimeContext:
    config = load_config(config_path)
    memory_store = CaseMemoryStore(config)
    instruction_loader = InstructionLoader(config, memory_store)
    mcp_override_resolver = (
        McpToolOverrideResolver.from_config(config)
        if config.tools.has_enabled_mcp_tools()
        else None
    )
    tool_registry = ToolRegistry(config, mcp_override_resolver=mcp_override_resolver)
    agent_factory = DeepAgentFactory(config, instruction_loader, tool_registry, memory_store)
    return RuntimeContext(
        config=config,
        memory_store=memory_store,
        instruction_loader=instruction_loader,
        tool_registry=tool_registry,
        agent_factory=agent_factory,
        case_id_resolver_service=CaseIdResolverService(),
    )


class RuntimeService:
    def __init__(self, context: RuntimeContext):
        self._context = context
        self._migrate_legacy_traces()
        intake_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(INTAKE_AGENT)}
        knowledge_retriever_tools = {
            tool.name: tool.handler for tool in context.tool_registry.get_tools(KNOWLEDGE_RETRIEVER_AGENT)
        }
        log_analyzer_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(LOG_ANALYZER_AGENT)}
        back_support_escalation_tools = {
            tool.name: tool.handler for tool in context.tool_registry.get_tools(BACK_SUPPORT_ESCALATION_AGENT)
        }
        back_support_inquiry_writer_tools = {
            tool.name: tool.handler for tool in context.tool_registry.get_tools(BACK_SUPPORT_INQUIRY_WRITER_AGENT)
        }
        draft_writer_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(DRAFT_WRITER_AGENT)}
        compliance_reviewer_tools = {
            tool.name: tool.handler for tool in context.tool_registry.get_tools(COMPLIANCE_REVIEWER_AGENT)
        }
        approval_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(APPROVAL_AGENT)}
        supervisor_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(SUPERVISOR_AGENT)}
        ticket_update_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(TICKET_UPDATE_AGENT)}
        self._intake_executor = IntakeAgent(
            config=context.config,
            pii_mask_tool=intake_tools["pii_mask"],
            external_ticket_tool=intake_tools["external_ticket"],
            internal_ticket_tool=intake_tools["internal_ticket"],
            classify_ticket_tool=intake_tools["classify_ticket"],
            write_shared_memory_tool=intake_tools["write_shared_memory"],
            write_working_memory_tool=intake_tools.get("write_working_memory"),
        )
        self._approval_executor = ApprovalAgent(
            record_approval_decision_tool=approval_tools["record_approval_decision"],
        )
        self._ticket_update_executor = TicketUpdateAgent(
            prepare_ticket_update_tool=ticket_update_tools["prepare_ticket_update"],
            zendesk_reply_tool=ticket_update_tools["zendesk_reply"],
            redmine_update_tool=ticket_update_tools["redmine_update"],
        )
        self._log_analyzer_executor = LogAnalyzerPhaseExecutor(
            detect_log_format_tool=log_analyzer_tools["detect_log_format"],
            write_working_memory_tool=log_analyzer_tools["write_working_memory"],
        )
        self._knowledge_retriever_executor = KnowledgeRetrieverPhaseExecutor(
            search_documents_tool=knowledge_retriever_tools["search_documents"],
            external_ticket_tool=knowledge_retriever_tools["external_ticket"],
            internal_ticket_tool=knowledge_retriever_tools["internal_ticket"],
            write_shared_memory_tool=knowledge_retriever_tools.get("write_shared_memory"),
            write_working_memory_tool=knowledge_retriever_tools["write_working_memory"],
            constraint_mode=context.config.agents.resolve_constraint_mode(KNOWLEDGE_RETRIEVER_AGENT),
        )
        self._back_support_escalation_executor = BackSupportEscalationPhaseExecutor(
            read_shared_memory_tool=back_support_escalation_tools["read_shared_memory"],
            write_shared_memory_tool=back_support_escalation_tools["write_shared_memory"],
        )
        self._back_support_inquiry_writer_executor = BackSupportInquiryWriterPhaseExecutor(
            write_shared_memory_tool=back_support_inquiry_writer_tools["write_shared_memory"],
            write_draft_tool=back_support_inquiry_writer_tools["write_draft"],
        )
        self._draft_writer_executor = DraftWriterPhaseExecutor(
            config=context.config,
            write_draft_tool=draft_writer_tools.get("write_draft") or back_support_inquiry_writer_tools["write_draft"],
        )
        self._compliance_reviewer_executor = ComplianceReviewerPhaseExecutor(
            check_policy_tool=compliance_reviewer_tools.get("check_policy") or build_default_check_policy_tool(context.config),
            request_revision_tool=compliance_reviewer_tools.get("request_revision") or build_default_request_revision_tool(),
            write_working_memory_tool=compliance_reviewer_tools.get("write_working_memory"),
            constraint_mode=context.config.agents.resolve_constraint_mode(COMPLIANCE_REVIEWER_AGENT),
        )
        self._supervisor_executor = SupervisorPhaseExecutor(
            read_shared_memory_tool=supervisor_tools["read_shared_memory"],
            write_shared_memory_tool=supervisor_tools["write_shared_memory"],
            draft_writer_executor=self._draft_writer_executor,
            log_analyzer_executor=self._log_analyzer_executor,
            knowledge_retriever_executor=self._knowledge_retriever_executor,
            compliance_reviewer_executor=self._compliance_reviewer_executor,
            back_support_escalation_executor=self._back_support_escalation_executor,
            back_support_inquiry_writer_executor=self._back_support_inquiry_writer_executor,
            escalation_settings=context.config.agents.BackSupportEscalationAgent.escalation,
            compliance_max_review_loops=context.config.agents.ComplianceReviewerAgent.max_review_loops,
            constraint_mode=context.config.agents.resolve_constraint_mode(SUPERVISOR_AGENT),
            max_investigation_loops=context.config.agents.SuperVisorAgent.max_investigation_loops,
        )

    @property
    def context(self) -> RuntimeContext:
        return self._context

    def resolve_case_id(
        self,
        *,
        prompt: str | None = None,
        case_id: str | None = None,
        workspace_path: str | None = None,
    ) -> str:
        return self._context.case_id_resolver_service.resolve(
            prompt or "",
            explicit_case_id=case_id,
            workspace_path=workspace_path,
        )

    @staticmethod
    def _coerce_workflow_kind(value: object) -> WorkflowKind:
        normalized = str(value or "").strip()
        if normalized in WORKFLOW_LABELS:
            return cast(WorkflowKind, normalized)
        return "ambiguous_case"

    def initialize_case(self, case_id: str, workspace_path: str) -> Path:
        case_paths = self._context.memory_store.initialize_case(case_id, workspace_path=workspace_path)
        for definition in self._context.agent_factory.build_default_definitions():
            self._context.memory_store.ensure_agent_working_memory(case_id, definition.role, workspace_path=workspace_path)
        return case_paths.root

    @staticmethod
    def _has_explicit_ticket_id(value: str | None) -> bool:
        return bool(value and value.strip())

    def _resolve_ticket_lookup_enabled(
        self,
        *,
        explicit_ticket_id: str | None,
        saved_ticket_id: object,
        saved_lookup_enabled: object,
        ticket_kind: str,
    ) -> bool:
        if self._has_explicit_ticket_id(explicit_ticket_id):
            return True
        if isinstance(saved_lookup_enabled, bool):
            return saved_lookup_enabled

        normalized_saved_ticket_id = str(saved_ticket_id or "").strip()
        if not normalized_saved_ticket_id:
            return False
        if ticket_kind == "external":
            return not self._context.case_id_resolver_service.is_auto_generated_external_ticket_id(normalized_saved_ticket_id)
        return not self._context.case_id_resolver_service.is_auto_generated_internal_ticket_id(normalized_saved_ticket_id)

    def describe_agents(self, case_id: str) -> list[dict[str, object]]:
        agents: list[dict[str, object]] = []
        for definition in self._context.agent_factory.build_default_definitions():
            agent = self._context.agent_factory.build_agent(case_id, definition)
            if isinstance(agent, dict):
                settings = self._context.agent_factory.get_agent_settings(definition.role)
                agent["config"] = settings.model_dump() if settings is not None else {}
                agents.append(agent)
            else:
                agents.append(
                    {
                        "role": definition.role,
                        "description": definition.description,
                        "kind": definition.kind,
                        "parent_role": definition.parent_role,
                    }
                )
        return agents

    def describe_control_catalog(self) -> dict[str, object]:
        return build_control_catalog(
            config=self._context.config,
            tool_registry=self._context.tool_registry,
            agent_definitions=self._context.agent_factory.build_default_definitions(),
        )

    def describe_runtime_audit(self, *, case_id: str, trace_id: str, workspace_path: str) -> dict[str, object]:
        state = self._load_state(case_id=case_id, trace_id=trace_id, workspace_path=workspace_path)
        if not state:
            raise ValueError("指定された trace_id の保存 state が見つかりません")
        return self._build_runtime_audit_for_state(case_id=case_id, state=state)

    def _build_runtime_audit_for_state(self, *, case_id: str, state: CaseState) -> dict[str, object]:
        return build_runtime_audit(
            case_id=case_id,
            state=state,
            config=self._context.config,
            instruction_loader=self._context.instruction_loader,
        )

    def list_cases(self, cases_root: str) -> list[dict[str, object]]:
        root = Path(cases_root).expanduser().resolve()
        if not root.exists():
            return []

        cases: list[dict[str, object]] = []
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_dir():
                continue
            marker = self._context.memory_store.read_case_id_marker(child)
            if marker is None and not (child / CASE_ID_FILENAME).exists():
                continue
            case_id = marker or child.name
            metadata = self._context.memory_store.read_case_metadata(child)
            history = self._context.memory_store.read_chat_history(case_id, str(child))
            case_title = str(metadata.get("case_title") or "").strip()
            if not case_title:
                case_title = self._backfill_case_title(case_id=case_id, workspace_path=str(child), history=history)
            cases.append(
                {
                    "case_id": case_id,
                    "case_title": case_title,
                    "workspace_path": str(child),
                    "updated_at": datetime.fromtimestamp(child.stat().st_mtime, tz=UTC).isoformat(),
                    "message_count": len(history),
                }
            )
        cases.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return cases

    def create_case(self, *, cases_root: str, prompt: str, case_id: str | None = None) -> dict[str, str]:
        selected_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id)
        workspace_path = Path(cases_root).expanduser().resolve() / selected_case_id
        case_path = self.initialize_case(selected_case_id, str(workspace_path))
        case_title = self._persist_case_title(
            case_id=selected_case_id,
            workspace_path=str(case_path),
            case_title=derive_case_title(prompt, fallback=selected_case_id),
        )
        return {"case_id": selected_case_id, "case_path": str(case_path), "case_title": case_title}

    def _persist_case_title(self, *, case_id: str, workspace_path: str, case_title: str | None) -> str:
        normalized = str(case_title or "").strip() or case_id
        self._context.memory_store.update_case_metadata(workspace_path, case_id=case_id, case_title=normalized)
        return normalized

    def _sync_case_title_from_state(self, *, case_id: str, workspace_path: str, state: dict[str, object], prompt: str) -> str:
        existing_title = str(self._context.memory_store.read_case_metadata(workspace_path).get("case_title") or "").strip()
        if existing_title:
            return existing_title
        case_title = str(state.get("case_title") or "").strip() or derive_case_title(prompt, fallback=case_id)
        return self._persist_case_title(case_id=case_id, workspace_path=workspace_path, case_title=case_title)

    def _backfill_case_title(self, *, case_id: str, workspace_path: str, history: list[dict[str, object]]) -> str:
        for message in history:
            if str(message.get("role") or "") != "user":
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            return self._persist_case_title(
                case_id=case_id,
                workspace_path=workspace_path,
                case_title=derive_case_title(content, fallback=case_id),
            )
        return self._persist_case_title(case_id=case_id, workspace_path=workspace_path, case_title=case_id)

    def get_chat_history(self, *, case_id: str, workspace_path: str) -> list[dict[str, object]]:
        return self._context.memory_store.read_chat_history(case_id, workspace_path)

    def list_workspace_entries(self, *, case_id: str, workspace_path: str, relative_path: str = ".") -> dict[str, object]:
        entries = self._context.memory_store.list_workspace_entries(case_id, workspace_path, relative_path)
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "current_path": "." if relative_path in {"", "."} else relative_path,
            "entries": entries,
        }

    def get_workspace_file(self, *, case_id: str, workspace_path: str, relative_path: str, max_chars: int = 16000) -> dict[str, object]:
        target = self._context.memory_store.resolve_workspace_path(case_id, workspace_path, relative_path)
        guessed_mime, _ = mimetypes.guess_type(target.name)
        mime_type = guessed_mime or "application/octet-stream"
        is_text = target.suffix.lower() in TEXT_FILE_SUFFIXES or mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/xml",
            "application/yaml",
        }

        if not is_text:
            return {
                "case_id": case_id,
                "workspace_path": workspace_path,
                "path": relative_path,
                "name": target.name,
                "mime_type": mime_type,
                "preview_available": False,
                "truncated": False,
                "content": None,
            }

        content = self._context.memory_store.read_workspace_text(case_id, workspace_path, relative_path, max_chars=max_chars)
        full_length = len(self._context.memory_store.read_workspace_text(case_id, workspace_path, relative_path, max_chars=None))
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "path": relative_path,
            "name": target.name,
            "mime_type": mime_type,
            "preview_available": True,
            "truncated": full_length > max_chars,
            "content": content,
        }

    def save_workspace_file(
        self,
        *,
        case_id: str,
        workspace_path: str,
        relative_dir: str,
        filename: str,
        content: bytes,
    ) -> dict[str, object]:
        safe_filename = Path(filename).name
        relative_path = str(Path(relative_dir or ".") / safe_filename)
        written = self._context.memory_store.write_workspace_file(case_id, workspace_path, relative_path, content)
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "path": written.relative_to(Path(workspace_path).expanduser().resolve()).as_posix(),
            "size": written.stat().st_size,
        }

    def create_workspace_archive(self, *, case_id: str, workspace_path: str) -> Path:
        case_paths = self._context.memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
        archive_path = case_paths.report_dir / f"{case_id}-workspace.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        import zipfile

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for child in case_paths.root.rglob("*"):
                if child.is_file():
                    archive.write(child, arcname=str(child.relative_to(case_paths.root.parent)))
        return archive_path

    def workspace_file_path(self, *, case_id: str, workspace_path: str, relative_path: str) -> Path:
        return self._context.memory_store.resolve_workspace_path(case_id, workspace_path, relative_path)

    def _append_chat_message(
        self,
        *,
        case_id: str,
        workspace_path: str,
        role: str,
        content: str,
        trace_id: str | None,
        event: str,
    ) -> None:
        normalized = content.strip()
        if not normalized:
            return
        self._context.memory_store.append_chat_history(
            case_id,
            workspace_path,
            {
                "role": role,
                "content": normalized,
                "trace_id": trace_id,
                "event": event,
                "created_at": datetime.now(tz=UTC).isoformat(),
            },
        )

    @staticmethod
    def _is_context_dependent_followup(prompt: str) -> bool:
        normalized = re.sub(r"\s+", " ", prompt).strip()
        if not normalized or len(normalized) > 40:
            return False
        generic_patterns = (
            "詳細を教えてください",
            "詳しく教えてください",
            "詳しくお願いします",
            "詳細をお願いします",
            "もっと詳しく",
            "詳細は",
        )
        if any(pattern in normalized for pattern in generic_patterns):
            return True
        return normalized in {"詳細", "詳しく", "詳細に", "詳しく教えて", "続きを教えてください"}

    def _resolve_followup_anchor_issue(self, *, case_id: str, workspace_path: str, saved_state: CaseState) -> str:
        history = self._resolve_saved_conversation_messages(
            case_id=case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
        )
        for message in reversed(deserialize_langchain_messages(history)):
            if message.type != "human":
                continue
            content = str(getattr(message, "text", message.content)).strip()
            if not content or self._is_context_dependent_followup(content):
                continue
            return content
        return str(saved_state.get("raw_issue") or "").strip()

    def _resolve_saved_conversation_messages(
        self,
        *,
        case_id: str,
        workspace_path: str,
        saved_state: CaseState,
    ) -> list[dict[str, object]]:
        state_messages = saved_state.get("conversation_messages")
        if isinstance(state_messages, list) and state_messages:
            return coerce_serialized_conversation_messages(state_messages)
        return coerce_serialized_conversation_messages(self.get_chat_history(case_id=case_id, workspace_path=workspace_path))

    def _resolve_followup_anchor_from_messages(self, messages: list[dict[str, object]], current_prompt: str) -> str:
        for message in reversed(deserialize_langchain_messages(messages)):
            if message.type != "human":
                continue
            content = str(getattr(message, "text", message.content)).strip()
            if not content:
                continue
            if content == current_prompt and self._is_context_dependent_followup(content):
                continue
            if self._is_context_dependent_followup(content):
                continue
            return content
        return ""

    def _build_conversation_messages(
        self,
        *,
        case_id: str,
        workspace_path: str,
        saved_state: CaseState,
        prompt: str,
        conversation_messages: list[dict[str, object]] | None = None,
        chat_history: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        request_messages = coerce_serialized_conversation_messages(conversation_messages)
        if request_messages:
            return append_serialized_message(request_messages, role="user", content=prompt)

        legacy_messages = coerce_serialized_conversation_messages(chat_history)
        if legacy_messages:
            return append_serialized_message(legacy_messages, role="user", content=prompt)

        saved_messages = self._resolve_saved_conversation_messages(
            case_id=case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
        )
        return append_serialized_message(saved_messages, role="user", content=prompt)

    def _resolve_action_prompt(
        self,
        *,
        prompt: str,
        case_id: str,
        workspace_path: str,
        saved_state: CaseState,
        conversation_messages: list[dict[str, object]] | None = None,
        chat_history: list[dict[str, object]] | None = None,
    ) -> str:
        normalized_prompt = prompt.strip()
        if not self._is_context_dependent_followup(normalized_prompt):
            return normalized_prompt

        request_messages = coerce_serialized_conversation_messages(conversation_messages)
        if not request_messages:
            request_messages = coerce_serialized_conversation_messages(chat_history)
        anchor_issue = self._resolve_followup_anchor_from_messages(request_messages, normalized_prompt)
        if not anchor_issue:
            anchor_issue = self._resolve_followup_anchor_issue(
                case_id=case_id,
                workspace_path=workspace_path,
                saved_state=saved_state,
            )
        if not anchor_issue or anchor_issue == normalized_prompt:
            return normalized_prompt
        return f"{anchor_issue}\n\n[Follow-up request]\n{normalized_prompt}"

    @staticmethod
    def _build_assistant_history_content(result: dict[str, object]) -> str:
        state = cast(dict[str, object], result.get("state") or {})
        candidates = [
            str(state.get("customer_response_draft") or "").strip(),
            str(state.get("draft_response") or "").strip(),
            str(state.get("next_action") or "").strip(),
            str(result.get("plan_summary") or "").strip(),
        ]
        for candidate in candidates:
            if candidate:
                return candidate
        status = str(state.get("status") or "").strip()
        return f"Workflow status: {status}" if status else "Workflow completed."

    def plan(
        self,
        *,
        prompt: str,
        workspace_path: str,
        case_id: str | None = None,
        external_ticket_id: str | None = None,
        internal_ticket_id: str | None = None,
    ) -> dict[str, object]:
        selected_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id, workspace_path=workspace_path)
        trace_id = self._new_trace_id()
        resolved_external_ticket_id = self._context.case_id_resolver_service.resolve_external_ticket_id(
            explicit_ticket_id=external_ticket_id,
            trace_id=trace_id,
        )
        resolved_internal_ticket_id = self._context.case_id_resolver_service.resolve_internal_ticket_id(
            explicit_ticket_id=internal_ticket_id,
            trace_id=trace_id,
        )
        external_ticket_lookup_enabled = self._has_explicit_ticket_id(external_ticket_id)
        internal_ticket_lookup_enabled = self._has_explicit_ticket_id(internal_ticket_id)
        self.initialize_case(selected_case_id, workspace_path=workspace_path)

        workflow_kind = route_workflow(prompt)
        plan_steps = build_plan_steps(workflow_kind)
        plan_summary = summarize_plan(workflow_kind)
        state: CaseState = {
            "case_id": selected_case_id,
            "workflow_run_id": trace_id,
            "trace_id": trace_id,
            "thread_id": trace_id,
            "workflow_kind": workflow_kind,
            "execution_mode": "plan",
            "workspace_path": workspace_path,
            "raw_issue": prompt,
            "conversation_messages": append_serialized_message([], role="user", content=prompt),
            "external_ticket_id": resolved_external_ticket_id,
            "internal_ticket_id": resolved_internal_ticket_id,
            "external_ticket_lookup_enabled": external_ticket_lookup_enabled,
            "internal_ticket_lookup_enabled": internal_ticket_lookup_enabled,
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
        }
        result = self._invoke_workflow(state, trace_id)
        self._sync_case_title_from_state(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            state=result,
            prompt=prompt,
        )
        report_path = self._maybe_auto_generate_report(
            case_id=selected_case_id,
            trace_id=trace_id,
            workspace_path=workspace_path,
            state=result,
        )
        response = {
            "case_id": selected_case_id,
            "trace_id": trace_id,
            "thread_id": trace_id,
            "workflow_run_id": trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "external_ticket_id": resolved_external_ticket_id,
            "internal_ticket_id": resolved_internal_ticket_id,
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
            "requires_approval": result.get("status") == "WAITING_APPROVAL",
            "requires_customer_input": result.get("status") == "WAITING_CUSTOMER_INPUT",
            "report_path": report_path,
            "state": result,
        }
        self._append_chat_message(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            role="user",
            content=prompt,
            trace_id=trace_id,
            event="plan",
        )
        self._append_chat_message(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            role="assistant",
            content=self._build_assistant_history_content(response),
            trace_id=trace_id,
            event="plan",
        )
        return response

    def action(
        self,
        *,
        prompt: str,
        workspace_path: str,
        case_id: str | None = None,
        trace_id: str | None = None,
        execution_plan: str | None = None,
        external_ticket_id: str | None = None,
        internal_ticket_id: str | None = None,
        conversation_messages: list[dict[str, object]] | None = None,
        chat_history: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        resolved_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id, workspace_path=workspace_path)
        saved_state = self._load_state(case_id=resolved_case_id, trace_id=trace_id, workspace_path=workspace_path)
        selected_case_id = str(saved_state.get("case_id") or resolved_case_id)
        current_trace_id = trace_id or str(saved_state.get("trace_id") or self._new_trace_id())
        resolved_external_ticket_id = self._context.case_id_resolver_service.resolve_external_ticket_id(
            explicit_ticket_id=external_ticket_id or str(saved_state.get("external_ticket_id") or "") or None,
            trace_id=current_trace_id,
        )
        resolved_internal_ticket_id = self._context.case_id_resolver_service.resolve_internal_ticket_id(
            explicit_ticket_id=internal_ticket_id or str(saved_state.get("internal_ticket_id") or "") or None,
            trace_id=current_trace_id,
        )
        external_ticket_lookup_enabled = self._resolve_ticket_lookup_enabled(
            explicit_ticket_id=external_ticket_id,
            saved_ticket_id=saved_state.get("external_ticket_id"),
            saved_lookup_enabled=saved_state.get("external_ticket_lookup_enabled"),
            ticket_kind="external",
        )
        internal_ticket_lookup_enabled = self._resolve_ticket_lookup_enabled(
            explicit_ticket_id=internal_ticket_id,
            saved_ticket_id=saved_state.get("internal_ticket_id"),
            saved_lookup_enabled=saved_state.get("internal_ticket_lookup_enabled"),
            ticket_kind="internal",
        )

        if not saved_state:
            workflow_kind = route_workflow(prompt)
            plan_steps = build_plan_steps(workflow_kind)
            plan_summary = execution_plan or summarize_plan(workflow_kind)
        else:
            workflow_kind = self._coerce_workflow_kind(saved_state.get("workflow_kind") or route_workflow(prompt))
            plan_steps = list(saved_state.get("plan_steps") or build_plan_steps(workflow_kind))
            plan_summary = str(saved_state.get("plan_summary") or execution_plan or summarize_plan(workflow_kind))

        self.initialize_case(selected_case_id, workspace_path=workspace_path)
        resolved_prompt = self._resolve_action_prompt(
            prompt=prompt,
            case_id=selected_case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
            conversation_messages=conversation_messages,
            chat_history=chat_history,
        )
        resolved_conversation_messages = self._build_conversation_messages(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
            prompt=prompt,
            conversation_messages=conversation_messages,
            chat_history=chat_history,
        )
        state: CaseState = {
            "case_id": selected_case_id,
            "workflow_run_id": current_trace_id,
            "trace_id": current_trace_id,
            "thread_id": current_trace_id,
            "workflow_kind": workflow_kind,  # type: ignore[typeddict-item]
            "execution_mode": "action",
            "workspace_path": workspace_path,
            "raw_issue": resolved_prompt,
            "conversation_messages": resolved_conversation_messages,
            "external_ticket_id": resolved_external_ticket_id,
            "internal_ticket_id": resolved_internal_ticket_id,
            "external_ticket_lookup_enabled": external_ticket_lookup_enabled,
            "internal_ticket_lookup_enabled": internal_ticket_lookup_enabled,
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
            "approval_decision": "pending",
        }
        result = self._invoke_workflow(state, current_trace_id)
        self._sync_case_title_from_state(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            state=result,
            prompt=prompt,
        )
        report_path = self._maybe_auto_generate_report(
            case_id=selected_case_id,
            trace_id=current_trace_id,
            workspace_path=workspace_path,
            state=result,
        )
        response = {
            "case_id": selected_case_id,
            "trace_id": current_trace_id,
            "thread_id": current_trace_id,
            "workflow_run_id": current_trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "execution_mode": "action",
            "external_ticket_id": resolved_external_ticket_id,
            "internal_ticket_id": resolved_internal_ticket_id,
            "requires_customer_input": result.get("status") == "WAITING_CUSTOMER_INPUT",
            "report_path": report_path,
            "state": result,
        }
        self._append_chat_message(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            role="user",
            content=prompt,
            trace_id=current_trace_id,
            event="action",
        )
        self._append_chat_message(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            role="assistant",
            content=self._build_assistant_history_content(response),
            trace_id=current_trace_id,
            event="action",
        )
        return response

    def resume_customer_input(
        self,
        *,
        case_id: str,
        trace_id: str,
        workspace_path: str,
        additional_input: str,
        answer_key: str | None = None,
        external_ticket_id: str | None = None,
        internal_ticket_id: str | None = None,
    ) -> dict[str, object]:
        saved_state = self._load_state(case_id=case_id, trace_id=trace_id, workspace_path=workspace_path)
        if not saved_state:
            raise ValueError("指定された trace_id の保存 state が見つかりません")

        if str(saved_state.get("status") or "") != "WAITING_CUSTOMER_INPUT":
            raise ValueError("指定された trace は顧客入力待ち状態ではありません")

        self.initialize_case(case_id, workspace_path=workspace_path)

        previous_issue = str(saved_state.get("raw_issue") or "").strip()
        merged_prompt = previous_issue
        normalized_additional_input = additional_input.strip()
        if normalized_additional_input:
            merged_prompt = f"{previous_issue}\n\n[Additional customer input]\n{normalized_additional_input}" if previous_issue else normalized_additional_input

        resumed_state = self._normalize_state_ids(saved_state, trace_id=trace_id)
        resumed_state["case_id"] = case_id
        resumed_state["workspace_path"] = workspace_path
        resumed_state["raw_issue"] = merged_prompt
        resumed_state["conversation_messages"] = append_serialized_message(
            self._resolve_saved_conversation_messages(case_id=case_id, workspace_path=workspace_path, saved_state=saved_state),
            role="user",
            content=normalized_additional_input,
        )
        resumed_state["external_ticket_id"] = self._context.case_id_resolver_service.resolve_external_ticket_id(
            explicit_ticket_id=external_ticket_id or str(saved_state.get("external_ticket_id") or "") or None,
            trace_id=trace_id,
        )
        resumed_state["internal_ticket_id"] = self._context.case_id_resolver_service.resolve_internal_ticket_id(
            explicit_ticket_id=internal_ticket_id or str(saved_state.get("internal_ticket_id") or "") or None,
            trace_id=trace_id,
        )
        resumed_state["external_ticket_lookup_enabled"] = self._resolve_ticket_lookup_enabled(
            explicit_ticket_id=external_ticket_id,
            saved_ticket_id=saved_state.get("external_ticket_id"),
            saved_lookup_enabled=saved_state.get("external_ticket_lookup_enabled"),
            ticket_kind="external",
        )
        resumed_state["internal_ticket_lookup_enabled"] = self._resolve_ticket_lookup_enabled(
            explicit_ticket_id=internal_ticket_id,
            saved_ticket_id=saved_state.get("internal_ticket_id"),
            saved_lookup_enabled=saved_state.get("internal_ticket_lookup_enabled"),
            ticket_kind="internal",
        )
        resumed_state["intake_rework_required"] = False
        resumed_state["intake_rework_reason"] = ""
        resumed_state["intake_missing_fields"] = []
        previous_questions = dict(saved_state.get("intake_followup_questions") or {})
        resolved_answer_key = answer_key
        if resolved_answer_key is None and len(previous_questions) == 1:
            resolved_answer_key = next(iter(previous_questions))
        if resolved_answer_key is None and len(previous_questions) > 1:
            raise ValueError("複数の追加入力項目があるため answer_key を指定してください")

        resumed_state["intake_followup_questions"] = {}
        answer_records = dict(saved_state.get("customer_followup_answers") or {})
        if normalized_additional_input:
            record_key = resolved_answer_key or "general"
            answer_records[record_key] = {
                "question": str(previous_questions.get(record_key) or ""),
                "answer": normalized_additional_input,
            }
            if record_key == "intake_incident_timeframe":
                resumed_state["intake_incident_timeframe"] = normalized_additional_input
        resumed_state["customer_followup_answers"] = answer_records
        resumed_state["next_action"] = "追加情報を反映して Intake subgraph を再実行する"

        result = self._invoke_workflow(resumed_state, trace_id)
        self._sync_case_title_from_state(
            case_id=case_id,
            workspace_path=workspace_path,
            state=result,
            prompt=merged_prompt,
        )
        report_path = self._maybe_auto_generate_report(
            case_id=case_id,
            trace_id=trace_id,
            workspace_path=workspace_path,
            state=result,
        )

        workflow_kind = self._coerce_workflow_kind(result.get("workflow_kind") or saved_state.get("workflow_kind"))

        response = {
            "case_id": case_id,
            "trace_id": trace_id,
            "thread_id": trace_id,
            "workflow_run_id": trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "execution_mode": str(result.get("execution_mode") or saved_state.get("execution_mode") or ""),
            "external_ticket_id": str(result.get("external_ticket_id") or resumed_state.get("external_ticket_id") or ""),
            "internal_ticket_id": str(result.get("internal_ticket_id") or resumed_state.get("internal_ticket_id") or ""),
            "plan_summary": str(result.get("plan_summary") or saved_state.get("plan_summary") or ""),
            "plan_steps": list(result.get("plan_steps") or saved_state.get("plan_steps") or []),
            "requires_approval": result.get("status") == "WAITING_APPROVAL",
            "requires_customer_input": result.get("status") == "WAITING_CUSTOMER_INPUT",
            "report_path": report_path,
            "state": result,
        }
        self._append_chat_message(
            case_id=case_id,
            workspace_path=workspace_path,
            role="user",
            content=additional_input,
            trace_id=trace_id,
            event="resume_customer_input",
        )
        self._append_chat_message(
            case_id=case_id,
            workspace_path=workspace_path,
            role="assistant",
            content=self._build_assistant_history_content(response),
            trace_id=trace_id,
            event="resume_customer_input",
        )
        return response

    def print_workflow_nodes(self) -> list[str]:
        graph = build_case_workflow(
            intake_executor=self._intake_executor,
            approval_executor=self._approval_executor,
            ticket_update_executor=self._ticket_update_executor,
            supervisor_executor=self._supervisor_executor,
        ).get_graph()
        return sorted(node.id for node in graph.nodes.values())

    def checkpoint_db_path(self, case_id: str, workspace_path: str) -> Path:
        case_paths = self._context.memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
        case_paths.traces_dir.mkdir(parents=True, exist_ok=True)
        return case_paths.traces_dir / self._context.config.data_paths.checkpoint_db_filename

    def report_file_path(self, case_id: str, trace_id: str, workspace_path: str) -> Path:
        case_paths = self._context.memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
        case_paths.report_dir.mkdir(parents=True, exist_ok=True)
        return case_paths.report_dir / f"support-improvement-{trace_id}.md"

    def checkpoint_status(
        self,
        *,
        case_id: str,
        workspace_path: str,
        trace_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        db_path = self.checkpoint_db_path(case_id, workspace_path)
        result: dict[str, object] = {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "checkpoint_db_path": str(db_path),
            "exists": db_path.exists(),
            "trace_ids": [],
            "checkpoint_count": 0,
        }
        if not db_path.exists():
            return result

        result["size_bytes"] = db_path.stat().st_size
        with sqlite3.connect(str(db_path)) as conn:
            checkpoint_count = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
            result["checkpoint_count"] = int(checkpoint_count[0]) if checkpoint_count else 0
            rows = conn.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            result["trace_ids"] = [str(row[0]) for row in rows]

        if trace_id:
            state = self._load_state(case_id=case_id, trace_id=trace_id, workspace_path=workspace_path)
            result["trace_id"] = trace_id
            result["has_trace"] = bool(state)
            if state:
                result["state_status"] = str(state.get("status") or "")
                result["workflow_kind"] = str(state.get("workflow_kind") or "")
        return result

    def generate_support_improvement_report(
        self,
        *,
        case_id: str,
        trace_id: str,
        workspace_path: str,
        checklist: list[str] | None = None,
    ) -> dict[str, object]:
        state = self._load_state(case_id=case_id, trace_id=trace_id, workspace_path=workspace_path)
        if not state:
            raise ValueError("指定された trace_id の保存 state が見つかりません")

        result = build_support_improvement_report(
            case_id=case_id,
            trace_id=trace_id,
            workspace_path=workspace_path,
            state=state,
            memory_store=self._context.memory_store,
            instruction_loader=self._context.instruction_loader,
            config=self._context.config,
            control_catalog=self.describe_control_catalog(),
            runtime_audit=self._build_runtime_audit_for_state(case_id=case_id, state=state),
            checklist=checklist,
        )
        return {
            "case_id": case_id,
            "trace_id": trace_id,
            "report_path": str(result.report_path),
            "sequence_diagram": result.sequence_diagram,
        }

    def _maybe_auto_generate_report(
        self,
        *,
        case_id: str,
        trace_id: str,
        workspace_path: str,
        state: CaseState,
    ) -> str | None:
        settings = self._context.config.agents.SuperVisorAgent
        if not settings.auto_generate_report:
            return None

        status = str(state.get("status") or "")
        trigger_map = {
            "WAITING_APPROVAL": "waiting_approval",
            "CLOSED": "closed",
        }
        trigger = trigger_map.get(status)
        if trigger is None or trigger not in settings.report_on:
            return None

        result = build_support_improvement_report(
            case_id=case_id,
            trace_id=trace_id,
            workspace_path=workspace_path,
            state=state,
            memory_store=self._context.memory_store,
            instruction_loader=self._context.instruction_loader,
            config=self._context.config,
            control_catalog=self.describe_control_catalog(),
            runtime_audit=self._build_runtime_audit_for_state(case_id=case_id, state=state),
            checklist=None,
        )
        return str(result.report_path)

    def _load_state(self, *, case_id: str | None, trace_id: str | None, workspace_path: str | None = None) -> CaseState:
        if not trace_id or not case_id or not workspace_path:
            return {}

        with self._workflow_checkpointer(case_id=case_id, workspace_path=workspace_path) as checkpointer:
            graph = build_case_workflow(
                checkpointer=checkpointer,
                intake_executor=self._intake_executor,
                approval_executor=self._approval_executor,
                ticket_update_executor=self._ticket_update_executor,
                supervisor_executor=self._supervisor_executor,
            )
            snapshot = graph.get_state({"configurable": {"thread_id": trace_id, "checkpoint_ns": ""}})
            return self._normalize_state_ids(cast(dict[str, object], snapshot.values), trace_id=trace_id)

    def _migrate_legacy_traces(self) -> None:
        return

    def _invoke_workflow(self, state: CaseState, trace_id: str) -> CaseState:
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        workflow_config = {"configurable": {"thread_id": trace_id, "checkpoint_ns": ""}}

        with self._workflow_checkpointer(case_id=case_id, workspace_path=workspace_path) as checkpointer:
            graph = build_case_workflow(
                checkpointer=checkpointer,
                intake_executor=self._intake_executor,
                approval_executor=self._approval_executor,
                ticket_update_executor=self._ticket_update_executor,
                supervisor_executor=self._supervisor_executor,
            )
            return cast(CaseState, graph.invoke(state, config=workflow_config))

    def _workflow_checkpointer(self, *, case_id: str, workspace_path: str):
        if not case_id or not workspace_path:
            raise ValueError("case_id and workspace_path are required to use the SQLite checkpointer")
        checkpoint_db_path = self.checkpoint_db_path(case_id, workspace_path)
        return SqliteSaver.from_conn_string(str(checkpoint_db_path))

    def _normalize_state_ids(self, state: dict[str, object] | CaseState, *, trace_id: str | None = None) -> CaseState:
        normalized_trace_id = self._normalize_trace_id(
            str(trace_id or state.get("trace_id") or state.get("session_id") or self._new_trace_id())
        )
        normalized_state = cast(CaseState, dict(state))
        normalized_state.pop("session_id", None)
        normalized_state["trace_id"] = normalized_trace_id
        normalized_state["thread_id"] = normalized_trace_id
        normalized_state["workflow_run_id"] = normalized_trace_id
        return normalized_state

    @staticmethod
    def _normalize_trace_id(value: str) -> str:
        if value.startswith("SESSION-"):
            return f"TRACE-{value.removeprefix('SESSION-')}"
        if value.startswith("TRACE-"):
            return value
        return f"TRACE-{value}"

    @staticmethod
    def _new_trace_id() -> str:
        return f"TRACE-{uuid4().hex}"