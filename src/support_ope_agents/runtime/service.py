from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from support_ope_agents.agents.intake_agent import IntakePhaseExecutor
from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor
from support_ope_agents.agents.supervisor_agent import SupervisorPhaseExecutor
from support_ope_agents.agents.roles import INTAKE_AGENT
from support_ope_agents.agents.roles import LOG_ANALYZER_AGENT
from support_ope_agents.agents.roles import SUPERVISOR_AGENT
from support_ope_agents.agents.deep_agent_factory import DeepAgentFactory
from support_ope_agents.config import AppConfig, load_config
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.tools import ToolRegistry
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
    mcp_override_resolver = McpToolOverrideResolver.from_config(config) if config.tools.has_overrides() else None
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
        log_analyzer_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(LOG_ANALYZER_AGENT)}
        supervisor_tools = {tool.name: tool.handler for tool in context.tool_registry.get_tools(SUPERVISOR_AGENT)}
        self._intake_executor = IntakePhaseExecutor(
            pii_mask_tool=intake_tools["pii_mask"],
            classify_ticket_tool=intake_tools["classify_ticket"],
            write_shared_memory_tool=intake_tools["write_shared_memory"],
        )
        self._log_analyzer_executor = LogAnalyzerPhaseExecutor(
            detect_log_format_tool=log_analyzer_tools["detect_log_format"],
        )
        self._supervisor_executor = SupervisorPhaseExecutor(
            read_shared_memory_tool=supervisor_tools["read_shared_memory"],
            write_shared_memory_tool=supervisor_tools["write_shared_memory"],
            log_analyzer_executor=self._log_analyzer_executor,
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

    def plan(self, *, prompt: str, workspace_path: str, case_id: str | None = None) -> dict[str, object]:
        selected_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id, workspace_path=workspace_path)
        trace_id = self._new_trace_id()
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
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
        }
        result = cast(
            CaseState,
            build_case_workflow(intake_executor=self._intake_executor, supervisor_executor=self._supervisor_executor).invoke(state),
        )
        self._save_state(selected_case_id, trace_id, result)
        return {
            "case_id": selected_case_id,
            "trace_id": trace_id,
            "thread_id": trace_id,
            "workflow_run_id": trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
            "requires_approval": result.get("status") == "WAITING_APPROVAL",
            "requires_customer_input": result.get("status") == "WAITING_CUSTOMER_INPUT",
            "state": result,
        }

    def action(
        self,
        *,
        prompt: str,
        workspace_path: str,
        case_id: str | None = None,
        trace_id: str | None = None,
        execution_plan: str | None = None,
    ) -> dict[str, object]:
        resolved_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id, workspace_path=workspace_path)
        saved_state = self._load_state(case_id=resolved_case_id, trace_id=trace_id, workspace_path=workspace_path)
        selected_case_id = str(saved_state.get("case_id") or resolved_case_id)
        current_trace_id = trace_id or str(saved_state.get("trace_id") or self._new_trace_id())

        if not saved_state:
            workflow_kind = route_workflow(prompt)
            plan_steps = build_plan_steps(workflow_kind)
            plan_summary = execution_plan or summarize_plan(workflow_kind)
        else:
            workflow_kind = self._coerce_workflow_kind(saved_state.get("workflow_kind") or route_workflow(prompt))
            plan_steps = list(saved_state.get("plan_steps") or build_plan_steps(workflow_kind))
            plan_summary = str(saved_state.get("plan_summary") or execution_plan or summarize_plan(workflow_kind))

        self.initialize_case(selected_case_id, workspace_path=workspace_path)
        state: CaseState = {
            "case_id": selected_case_id,
            "workflow_run_id": current_trace_id,
            "trace_id": current_trace_id,
            "thread_id": current_trace_id,
            "workflow_kind": workflow_kind,  # type: ignore[typeddict-item]
            "execution_mode": "action",
            "workspace_path": workspace_path,
            "raw_issue": prompt,
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
            "approval_decision": "pending",
        }
        result = cast(
            CaseState,
            build_case_workflow(intake_executor=self._intake_executor, supervisor_executor=self._supervisor_executor).invoke(state),
        )
        self._save_state(selected_case_id, current_trace_id, result)
        return {
            "case_id": selected_case_id,
            "trace_id": current_trace_id,
            "thread_id": current_trace_id,
            "workflow_run_id": current_trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "execution_mode": "action",
            "requires_customer_input": result.get("status") == "WAITING_CUSTOMER_INPUT",
            "state": result,
        }

    def resume_customer_input(
        self,
        *,
        case_id: str,
        trace_id: str,
        workspace_path: str,
        additional_input: str,
        answer_key: str | None = None,
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
        resumed_state["customer_followup_answers"] = answer_records
        resumed_state["next_action"] = "追加情報を反映して Intake を再実行する"

        result = cast(
            CaseState,
            build_case_workflow(intake_executor=self._intake_executor, supervisor_executor=self._supervisor_executor).invoke(resumed_state),
        )
        self._save_state(case_id, trace_id, result)

        workflow_kind = self._coerce_workflow_kind(result.get("workflow_kind") or saved_state.get("workflow_kind"))

        return {
            "case_id": case_id,
            "trace_id": trace_id,
            "thread_id": trace_id,
            "workflow_run_id": trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "execution_mode": str(result.get("execution_mode") or saved_state.get("execution_mode") or ""),
            "plan_summary": str(result.get("plan_summary") or saved_state.get("plan_summary") or ""),
            "plan_steps": list(result.get("plan_steps") or saved_state.get("plan_steps") or []),
            "requires_approval": result.get("status") == "WAITING_APPROVAL",
            "requires_customer_input": result.get("status") == "WAITING_CUSTOMER_INPUT",
            "state": result,
        }

    def print_workflow_nodes(self) -> list[str]:
        graph = build_case_workflow(intake_executor=self._intake_executor, supervisor_executor=self._supervisor_executor).get_graph()
        return sorted(node.id for node in graph.nodes.values())

    def state_file_path(self, case_id: str, trace_id: str, workspace_path: str) -> Path:
        case_paths = self._context.memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
        state_dir = case_paths.root / "traces"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{trace_id}.json"

    def _save_state(self, case_id: str, trace_id: str, state: CaseState) -> None:
        workspace_path = str(state.get("workspace_path") or "").strip()
        if not workspace_path:
            raise ValueError("workspace_path is required to save state")
        state_path = self.state_file_path(case_id, trace_id, workspace_path=workspace_path)
        normalized_state = self._normalize_state_ids(state, trace_id=trace_id)
        state_path.write_text(json.dumps(normalized_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_state(self, *, case_id: str | None, trace_id: str | None, workspace_path: str | None = None) -> CaseState:
        if not trace_id:
            return {}

        if not workspace_path:
            return {}

        if case_id:
            state_path = self.state_file_path(case_id, trace_id, workspace_path=workspace_path)
            if state_path.exists():
                loaded_state = json.loads(state_path.read_text(encoding="utf-8"))
                return self._normalize_state_ids(loaded_state, trace_id=trace_id)
            return {}
        return {}

    def _migrate_legacy_traces(self) -> None:
        return

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