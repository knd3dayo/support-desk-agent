from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from support_ope_agents.agents import DeepAgentFactory
from support_ope_agents.config import AppConfig, load_config
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools import ToolRegistry
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


def build_runtime_context(config_path: str) -> RuntimeContext:
    config = load_config(config_path)
    memory_store = CaseMemoryStore(config)
    instruction_loader = InstructionLoader(config, memory_store)
    tool_registry = ToolRegistry(config)
    agent_factory = DeepAgentFactory(config, instruction_loader, tool_registry, memory_store)
    return RuntimeContext(
        config=config,
        memory_store=memory_store,
        instruction_loader=instruction_loader,
        tool_registry=tool_registry,
        agent_factory=agent_factory,
    )


class RuntimeService:
    def __init__(self, context: RuntimeContext):
        self._context = context

    @property
    def context(self) -> RuntimeContext:
        return self._context

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
                agent["config"] = self._context.config.agents.get(definition.role).model_dump() if definition.role in self._context.config.agents else {}
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
        selected_case_id = case_id or self._new_case_id()
        session_id = self._new_session_id()
        self.initialize_case(selected_case_id, workspace_path=workspace_path)

        workflow_kind = route_workflow(prompt)
        plan_steps = build_plan_steps(workflow_kind)
        plan_summary = summarize_plan(workflow_kind)
        state: CaseState = {
            "case_id": selected_case_id,
            "session_id": session_id,
            "workflow_run_id": session_id,
            "trace_id": session_id,
            "thread_id": session_id,
            "workflow_kind": workflow_kind,
            "execution_mode": "plan",
            "workspace_path": workspace_path,
            "raw_issue": prompt,
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
        }
        result = build_case_workflow().invoke(state)
        self._save_session(selected_case_id, session_id, result)
        return {
            "case_id": selected_case_id,
            "session_id": session_id,
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
        session_id: str | None = None,
        execution_plan: str | None = None,
    ) -> dict[str, object]:
        session_state = self._load_session(case_id=case_id, session_id=session_id)
        selected_case_id = case_id or str(session_state.get("case_id") or self._new_case_id())
        current_session_id = session_id or str(session_state.get("session_id") or self._new_session_id())

        if not session_state:
            workflow_kind = route_workflow(prompt)
            plan_steps = build_plan_steps(workflow_kind)
            plan_summary = execution_plan or summarize_plan(workflow_kind)
        else:
            workflow_kind = str(session_state.get("workflow_kind") or route_workflow(prompt))
            plan_steps = list(session_state.get("plan_steps") or build_plan_steps(workflow_kind))
            plan_summary = str(session_state.get("plan_summary") or execution_plan or summarize_plan(workflow_kind))

        self.initialize_case(selected_case_id, workspace_path=workspace_path)
        state: CaseState = {
            "case_id": selected_case_id,
            "session_id": current_session_id,
            "workflow_run_id": current_session_id,
            "trace_id": str(session_state.get("trace_id") or current_session_id),
            "thread_id": str(session_state.get("thread_id") or current_session_id),
            "workflow_kind": workflow_kind,  # type: ignore[typeddict-item]
            "execution_mode": "action",
            "workspace_path": workspace_path,
            "raw_issue": prompt,
            "plan_summary": plan_summary,
            "plan_steps": plan_steps,
            "approval_decision": "pending",
        }
        result = build_case_workflow().invoke(state)
        self._save_session(selected_case_id, current_session_id, result)
        return {
            "case_id": selected_case_id,
            "session_id": current_session_id,
            "workflow_kind": workflow_kind,
            "workflow_label": WORKFLOW_LABELS[workflow_kind],
            "execution_mode": "action",
            "state": result,
        }

    def print_workflow_nodes(self) -> list[str]:
        graph = build_case_workflow().get_graph()
        return sorted(node.id for node in graph.nodes.values())

    def session_file_path(self, case_id: str, session_id: str) -> Path:
        case_paths = self._context.memory_store.resolve_case_paths(case_id)
        sessions_dir = case_paths.root / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        return sessions_dir / f"{session_id}.json"

    def _save_session(self, case_id: str, session_id: str, state: CaseState) -> None:
        session_path = self.session_file_path(case_id, session_id)
        session_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_session(self, *, case_id: str | None, session_id: str | None) -> CaseState:
        if not case_id or not session_id:
            return {}
        session_path = self.session_file_path(case_id, session_id)
        if not session_path.exists():
            return {}
        return json.loads(session_path.read_text(encoding="utf-8"))

    @staticmethod
    def _new_case_id() -> str:
        return f"CASE-{uuid4().hex[:8].upper()}"

    @staticmethod
    def _new_session_id() -> str:
        return f"SESSION-{uuid4().hex}"