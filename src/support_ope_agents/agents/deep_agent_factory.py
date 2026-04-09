from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    COMPLIANCE_REVIEWER_SPECIALIST,
    DRAFT_WRITER_SPECIALIST,
    INTAKE_AGENT,
    INVESTIGATION_AGENT,
    KNOWLEDGE_RETRIEVER_SPECIALIST,
    LOG_ANALYZER_SPECIALIST,
    RESOLUTION_AGENT,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
    canonical_role,
)
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools import ToolRegistry

try:
    from deepagents import create_deep_agent
except Exception:  # pragma: no cover
    create_deep_agent = None


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    role: str
    description: str
    kind: str = "agent"
    parent_role: str | None = None


class DeepAgentFactory:
    def __init__(
        self,
        config: AppConfig,
        instruction_loader: InstructionLoader,
        tool_registry: ToolRegistry,
        memory_store: CaseMemoryStore,
    ):
        self._config = config
        self._instruction_loader = instruction_loader
        self._tool_registry = tool_registry
        self._memory_store = memory_store

    def build_agent(self, case_id: str, definition: AgentDefinition) -> Any:
        role = canonical_role(definition.role)
        system_prompt = self._instruction_loader.load(case_id, role)
        tools = self._tool_registry.get_tools(role)
        self._memory_store.ensure_agent_working_memory(case_id, role)
        model_name = self._config.agents.get(role).model if role in self._config.agents else None
        selected_model = model_name or self._config.llm.model

        if create_deep_agent is None:
            return {
                "role": role,
                "description": definition.description,
                "kind": definition.kind,
                "parent_role": definition.parent_role,
                "system_prompt": system_prompt,
                "tools": [tool.name for tool in tools],
            }

        try:
            return create_deep_agent(
                tools=[tool.handler for tool in tools],
                system_prompt=system_prompt,
                model=selected_model,
            )
        except Exception as exc:
            return {
                "role": role,
                "description": definition.description,
                "kind": definition.kind,
                "parent_role": definition.parent_role,
                "system_prompt": system_prompt,
                "tools": [tool.name for tool in tools],
                "runtime_warning": str(exc),
            }

    def build_default_definitions(self) -> list[AgentDefinition]:
        return [
            AgentDefinition(SUPERVISOR_AGENT, "Supervise the full support workflow", kind="supervisor"),
            AgentDefinition(INTAKE_AGENT, "Triage and initialize the case", kind="phase", parent_role=SUPERVISOR_AGENT),
            AgentDefinition(INVESTIGATION_AGENT, "Plan investigation and orchestrate specialists", kind="phase", parent_role=SUPERVISOR_AGENT),
            AgentDefinition(LOG_ANALYZER_SPECIALIST, "Analyze technical logs", kind="specialist", parent_role=INVESTIGATION_AGENT),
            AgentDefinition(KNOWLEDGE_RETRIEVER_SPECIALIST, "Search knowledge sources", kind="specialist", parent_role=INVESTIGATION_AGENT),
            AgentDefinition(RESOLUTION_AGENT, "Synthesize findings and coordinate draft", kind="phase", parent_role=SUPERVISOR_AGENT),
            AgentDefinition(DRAFT_WRITER_SPECIALIST, "Write customer-facing draft response", kind="specialist", parent_role=RESOLUTION_AGENT),
            AgentDefinition(COMPLIANCE_REVIEWER_SPECIALIST, "Review draft against policy", kind="specialist", parent_role=RESOLUTION_AGENT),
            AgentDefinition(APPROVAL_AGENT, "Manage human approval and reinvestigation decisions", kind="phase", parent_role=SUPERVISOR_AGENT),
            AgentDefinition(TICKET_UPDATE_AGENT, "Write external ticket updates", kind="phase", parent_role=SUPERVISOR_AGENT),
        ]