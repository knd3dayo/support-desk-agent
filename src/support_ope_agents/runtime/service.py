from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from support_ope_agents.agents.deep_agent_factory import DeepAgentFactory
from support_ope_agents.config import AppConfig, load_config
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverTool
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
    case_id_resolver: CaseIdResolverTool


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
        case_id_resolver=CaseIdResolverTool(),
    )


class RuntimeService:
    def __init__(self, context: RuntimeContext):
        self._context = context
        self._migrate_legacy_traces()

    @property
    def context(self) -> RuntimeContext:
        return self._context

    def resolve_case_id(self, *, prompt: str | None = None, case_id: str | None = None) -> str:
        return self._context.case_id_resolver.resolve(prompt or "", explicit_case_id=case_id)

    def initialize_case(self, case_id: str, workspace_path: str | None = None) -> Path:
        case_paths = self._context.memory_store.initialize_case(case_id, workspace_path=workspace_path)
        for definition in self._context.agent_factory.build_default_definitions():
            self._context.memory_store.ensure_agent_working_memory(case_id, definition.role)
            self._context.instruction_loader.ensure_override_file(case_id, definition.role)
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
        selected_case_id = self.resolve_case_id(prompt=prompt, case_id=case_id)
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
        result = build_case_workflow().invoke(state)
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
            "requires_approval": True,
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
        saved_state = self._load_state(case_id=case_id, trace_id=trace_id)
        selected_case_id = case_id or str(saved_state.get("case_id") or self.resolve_case_id(prompt=prompt))
        current_trace_id = trace_id or str(saved_state.get("trace_id") or self._new_trace_id())

        if not saved_state:
            workflow_kind = route_workflow(prompt)
            plan_steps = build_plan_steps(workflow_kind)
            plan_summary = execution_plan or summarize_plan(workflow_kind)
        else:
            workflow_kind = str(saved_state.get("workflow_kind") or route_workflow(prompt))
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
        result = build_case_workflow().invoke(state)
        self._save_state(selected_case_id, current_trace_id, result)
        return {
            "case_id": selected_case_id,
            "trace_id": current_trace_id,
            "thread_id": current_trace_id,
            "workflow_run_id": current_trace_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "execution_mode": "action",
            "state": result,
        }

    def print_workflow_nodes(self) -> list[str]:
        graph = build_case_workflow().get_graph()
        return sorted(node.id for node in graph.nodes.values())

    def state_file_path(self, case_id: str, trace_id: str) -> Path:
        case_paths = self._context.memory_store.resolve_case_paths(case_id)
        state_dir = case_paths.root / "traces"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{trace_id}.json"

    def _save_state(self, case_id: str, trace_id: str, state: CaseState) -> None:
        state_path = self.state_file_path(case_id, trace_id)
        normalized_state = self._normalize_state_ids(state, trace_id=trace_id)
        state_path.write_text(json.dumps(normalized_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_state(self, *, case_id: str | None, trace_id: str | None) -> CaseState:
        if not trace_id:
            return {}

        if case_id:
            state_path = self.state_file_path(case_id, trace_id)
            if state_path.exists():
                loaded_state = json.loads(state_path.read_text(encoding="utf-8"))
                return self._normalize_state_ids(loaded_state, trace_id=trace_id)
            return {}

        workspace_root = self._context.config.paths.workspace_root
        for candidate in workspace_root.glob(f"*/traces/{trace_id}.json"):
            if candidate.exists():
                loaded_state = json.loads(candidate.read_text(encoding="utf-8"))
                return self._normalize_state_ids(loaded_state, trace_id=trace_id)
        return {}

    def _migrate_legacy_traces(self) -> None:
        workspace_root = self._context.config.paths.workspace_root
        for legacy_dir in workspace_root.glob("*/sessions"):
            case_root = legacy_dir.parent
            trace_dir = case_root / "traces"
            trace_dir.mkdir(parents=True, exist_ok=True)
            for legacy_file in legacy_dir.glob("*.json"):
                loaded_state = json.loads(legacy_file.read_text(encoding="utf-8"))
                normalized_trace_id = self._normalize_trace_id(
                    str(loaded_state.get("trace_id") or loaded_state.get("session_id") or legacy_file.stem)
                )
                normalized_state = self._normalize_state_ids(loaded_state, trace_id=normalized_trace_id)
                trace_file = trace_dir / f"{normalized_trace_id}.json"
                trace_file.write_text(json.dumps(normalized_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                legacy_file.unlink()
            if not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()

    def _normalize_state_ids(self, state: dict[str, object], *, trace_id: str | None = None) -> CaseState:
        normalized_trace_id = self._normalize_trace_id(
            str(trace_id or state.get("trace_id") or state.get("session_id") or self._new_trace_id())
        )
        normalized_state: CaseState = dict(state)
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