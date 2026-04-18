from __future__ import annotations

import mimetypes
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.sqlite import SqliteSaver

from support_ope_agents.agents.catalog import build_default_agent_definitions
from support_ope_agents.agents.sample.sample_approval_agent import SampleApprovalAgent
from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_ope_agents.agents.sample.sample_intake_agent import SampleIntakeAgent
from support_ope_agents.agents.sample.sample_supervisor_agent import SampleSupervisorAgent
from support_ope_agents.agents.sample.sample_ticket_update_agent import SampleTicketUpdateAgent
from support_ope_agents.agents.roles import DEFAULT_AGENT_ROLES
from support_ope_agents.config import AppConfig, load_config
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.models.state_transitions import CaseStatuses, NextActionTexts, ReportStatusTriggers
from support_ope_agents.runtime.abstract_service import AbstractRuntimeContext
from support_ope_agents.runtime.abstract_service import AbstractRuntimeService
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.runtime.case_titles import derive_case_title
from support_ope_agents.runtime.conversation_messages import append_serialized_message, coerce_serialized_conversation_messages
from support_ope_agents.runtime.control_catalog import build_control_catalog, build_runtime_audit
from support_ope_agents.runtime.followup_context import build_conversation_messages
from support_ope_agents.runtime.followup_context import resolve_action_prompt
from support_ope_agents.runtime.followup_context import resolve_saved_conversation_messages
from support_ope_agents.runtime.reporting import build_support_improvement_report
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.runtime.service_support import append_chat_message
from support_ope_agents.runtime.service_support import backfill_case_title
from support_ope_agents.runtime.service_support import build_assistant_history_content
from support_ope_agents.runtime.service_support import has_explicit_ticket_id
from support_ope_agents.runtime.service_support import new_trace_id
from support_ope_agents.runtime.service_support import normalize_state_ids
from support_ope_agents.runtime.service_support import normalize_trace_id
from support_ope_agents.runtime.service_support import persist_case_title
from support_ope_agents.runtime.service_support import resolve_ticket_lookup_enabled
from support_ope_agents.runtime.service_support import sync_case_title_from_state
from support_ope_agents.runtime.case_id_resolver import CASE_ID_FILENAME
from support_ope_agents.tools import ToolRegistry
from support_ope_agents.tools.builtin_tools import TEXT_FILE_SUFFIXES
from support_ope_agents.tools.default_prepare_ticket_update import build_default_prepare_ticket_update_tool
from support_ope_agents.tools.mcp_client import McpToolClient
from support_ope_agents.tools.mcp_xml_toolset import XmlMcpToolsetProvider
from support_ope_agents.workflow import (
    WORKFLOW_LABELS,
    build_plan_steps,
    route_workflow,
    summarize_plan,
)
from support_ope_agents.workflow.sample.sample_case_workflow import CaseWorkflow as SampleCaseWorkflow
from support_ope_agents.models.state import CaseState, WorkflowKind


class SampleRuntimeContext(AbstractRuntimeContext):
    pass


def build_runtime_context(config_path: str) -> SampleRuntimeContext:
    config = load_config(config_path)
    memory_store = CaseMemoryStore(config)
    runtime_harness_manager = RuntimeHarnessManager(config)
    instruction_loader = InstructionLoader(config, memory_store, runtime_harness_manager)
    mcp_tool_client = McpToolClient.from_config(config) if config.tools.mcp_manifest_path is not None else None
    tool_registry = ToolRegistry(config, mcp_tool_client=mcp_tool_client)
    context = SampleRuntimeContext(
        config,
        memory_store,
        runtime_harness_manager,
        instruction_loader,
        tool_registry,
        CaseIdResolverService(),
    )
    return context


class SampleRuntimeService(AbstractRuntimeService[SampleRuntimeContext]):
    def __init__(self, context: SampleRuntimeContext):
        super().__init__(context)
        self._migrate_legacy_traces()
        ticket_mcp_provider = XmlMcpToolsetProvider.from_config(context.config)
        self._intake_executor = SampleIntakeAgent(config=context.config, ticket_mcp_provider=ticket_mcp_provider)
        self._approval_executor = SampleApprovalAgent()
        self._ticket_update_executor = SampleTicketUpdateAgent(
            config=context.config,
            ticket_mcp_provider=ticket_mcp_provider,
            prepare_ticket_update_tool=build_default_prepare_ticket_update_tool(context.config),
        )
        self._investigate_executor = SampleInvestigateAgent(config=context.config)
        self._supervisor_executor = SampleSupervisorAgent(
            investigate_executor=self._investigate_executor,
            back_support_escalation_executor=None,
        )

    def describe_agents(self, case_id: str) -> list[dict[str, object]]:
        agents: list[dict[str, object]] = []
        for definition in build_default_agent_definitions():
            settings = self._context.config.agents.get(definition.role)
            agents.append(
                {
                    "role": definition.role,
                    "description": definition.description,
                    "kind": definition.kind,
                    "parent_role": definition.parent_role,
                    "config": settings.model_dump() if settings is not None else {},
                    "case_id": case_id,
                }
            )
        return agents

    def describe_control_catalog(self) -> dict[str, object]:
        return build_control_catalog(
            config=self._context.config,
            tool_registry=self._context.tool_registry,
            agent_definitions=build_default_agent_definitions(),
            runtime_harness_manager=self._context.runtime_harness_manager,
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
            runtime_harness_manager=self._context.runtime_harness_manager,
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
            updated_at = str(metadata.get("updated_at") or "").strip()
            if not updated_at:
                updated_at = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC).isoformat()
            if not case_title:
                case_title = self._backfill_case_title(case_id=case_id, workspace_path=str(child), history=history)
                metadata = self._context.memory_store.read_case_metadata(child)
                updated_at = str(metadata.get("updated_at") or updated_at).strip() or updated_at
            cases.append(
                {
                    "case_id": case_id,
                    "case_title": case_title,
                    "workspace_path": str(child),
                    "updated_at": updated_at,
                    "message_count": len(history),
                }
            )
        cases.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return cases

    def create_case(self, *, cases_root: str, prompt: str, case_id: str | None = None) -> dict[str, str]:
        selected_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id)
        workspace_path = Path(cases_root).expanduser().resolve() / selected_case_id
        case_path = self.initialize_case(selected_case_id, str(workspace_path))
        self._context.memory_store.touch_case(str(case_path))
        case_title = self._persist_case_title(
            case_id=selected_case_id,
            workspace_path=str(case_path),
            case_title=derive_case_title(prompt, fallback=selected_case_id),
        )
        return {"case_id": selected_case_id, "case_path": str(case_path), "case_title": case_title}

    def _persist_case_title(self, *, case_id: str, workspace_path: str, case_title: str | None) -> str:
        return persist_case_title(
            memory_store=self._context.memory_store,
            case_id=case_id,
            workspace_path=workspace_path,
            case_title=case_title,
        )

    def _sync_case_title_from_state(self, *, case_id: str, workspace_path: str, state: CaseState, prompt: str) -> str:
        return sync_case_title_from_state(
            memory_store=self._context.memory_store,
            case_id=case_id,
            workspace_path=workspace_path,
            state=state,
            prompt=prompt,
        )

    def _backfill_case_title(self, *, case_id: str, workspace_path: str, history: list[dict[str, object]]) -> str:
        return backfill_case_title(
            memory_store=self._context.memory_store,
            case_id=case_id,
            workspace_path=workspace_path,
            history=history,
        )

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

    def get_workspace_file(self, *, case_id: str, workspace_path: str, relative_path: str, max_chars: int | None = None) -> dict[str, object]:
        target = self._context.memory_store.resolve_workspace_path(case_id, workspace_path, relative_path)
        effective_max_chars = max_chars
        if effective_max_chars is None:
            effective_max_chars = self._context.runtime_harness_manager.get_int_policy_value(
                "runtime.workspace_preview_max_chars",
                default=16000,
            )
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

        content = self._context.memory_store.read_workspace_text(
            case_id,
            workspace_path,
            relative_path,
            max_chars=effective_max_chars,
        )
        full_length = len(self._context.memory_store.read_workspace_text(case_id, workspace_path, relative_path, max_chars=None))
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "path": relative_path,
            "name": target.name,
            "mime_type": mime_type,
            "preview_available": True,
            "truncated": full_length > effective_max_chars,
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
        append_chat_message(
            memory_store=self._context.memory_store,
            case_id=case_id,
            workspace_path=workspace_path,
            role=role,
            content=content,
            trace_id=trace_id,
            event=event,
        )

    def _resolve_saved_conversation_messages(
        self,
        *,
        case_id: str,
        workspace_path: str,
        saved_state: CaseState,
    ) -> list[dict[str, object]]:
        return resolve_saved_conversation_messages(
            state_messages=saved_state.get("conversation_messages"),
            history=self.get_chat_history(case_id=case_id, workspace_path=workspace_path),
        )

    def _build_conversation_messages(
        self,
        *,
        case_id: str,
        workspace_path: str,
        saved_state: CaseState,
        prompt: str,
        conversation_messages: list[dict[str, object]] | None = None,
    ) -> list[dict[str, object]]:
        saved_messages = self._resolve_saved_conversation_messages(
            case_id=case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
        )
        return build_conversation_messages(
            prompt=prompt,
            request_messages=conversation_messages,
            saved_messages=saved_messages,
        )

    def _resolve_action_prompt(
        self,
        *,
        prompt: str,
        case_id: str,
        workspace_path: str,
        saved_state: CaseState,
        conversation_messages: list[dict[str, object]] | None = None,
    ) -> str:
        saved_messages = self._resolve_saved_conversation_messages(
            case_id=case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
        )
        return resolve_action_prompt(
            prompt=prompt,
            request_messages=conversation_messages,
            saved_messages=saved_messages,
            fallback_raw_issue=saved_state.get("raw_issue"),
        )

    @staticmethod
    def _build_assistant_history_content(result: dict[str, object]) -> str:
        return build_assistant_history_content(result)

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
        external_ticket_lookup_enabled = has_explicit_ticket_id(external_ticket_id)
        internal_ticket_lookup_enabled = has_explicit_ticket_id(internal_ticket_id)
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
            "requires_approval": result.get("status") == CaseStatuses.WAITING_APPROVAL,
            "requires_customer_input": result.get("status") == CaseStatuses.WAITING_CUSTOMER_INPUT,
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
        )
        resolved_conversation_messages = self._build_conversation_messages(
            case_id=selected_case_id,
            workspace_path=workspace_path,
            saved_state=saved_state,
            prompt=prompt,
            conversation_messages=conversation_messages,
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
            "requires_customer_input": result.get("status") == CaseStatuses.WAITING_CUSTOMER_INPUT,
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

        if str(saved_state.get("status") or "") != CaseStatuses.WAITING_CUSTOMER_INPUT:
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
        resumed_state["next_action"] = NextActionTexts.RESUME_INTAKE

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
            "requires_approval": result.get("status") == CaseStatuses.WAITING_APPROVAL,
            "requires_customer_input": result.get("status") == CaseStatuses.WAITING_CUSTOMER_INPUT,
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
        graph = SampleCaseWorkflow().build_case_workflow(
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
        trigger = ReportStatusTriggers.BY_STATUS.get(status)
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
            graph = self._build_case_workflow(checkpointer=checkpointer)
            snapshot = graph.get_state({"configurable": {"thread_id": trace_id, "checkpoint_ns": ""}})
            return self._normalize_state_ids(cast(dict[str, object], snapshot.values), trace_id=trace_id)

    def _build_case_workflow(self, *, checkpointer: object | None = None) -> Any:
        return SampleCaseWorkflow().build_case_workflow(
            checkpointer=cast(Any, checkpointer),
            intake_executor=self._intake_executor,
            approval_executor=self._approval_executor,
            ticket_update_executor=self._ticket_update_executor,
            supervisor_executor=self._supervisor_executor,
        )

    def _migrate_legacy_traces(self) -> None:
        return