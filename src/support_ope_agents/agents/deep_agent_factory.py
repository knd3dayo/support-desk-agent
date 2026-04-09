from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
        system_prompt = self._instruction_loader.load(case_id, definition.role)
        tools = self._tool_registry.get_tools(definition.role)
        self._memory_store.ensure_agent_working_memory(case_id, definition.role)

        if create_deep_agent is None:
            return {
                "role": definition.role,
                "description": definition.description,
                "system_prompt": system_prompt,
                "tools": [tool.name for tool in tools],
            }

        try:
            return create_deep_agent(
                tools=[tool.handler for tool in tools],
                system_prompt=system_prompt,
                model=self._config.llm.model,
            )
        except Exception as exc:
            return {
                "role": definition.role,
                "description": definition.description,
                "system_prompt": system_prompt,
                "tools": [tool.name for tool in tools],
                "runtime_warning": str(exc),
            }

    def build_default_definitions(self) -> list[AgentDefinition]:
        return [
            AgentDefinition("intake_supervisor", "Triage and initialize the case"),
            AgentDefinition("investigation_supervisor", "Plan investigation and spawn specialists"),
            AgentDefinition("log_analyzer", "Analyze technical logs"),
            AgentDefinition("knowledge_retriever", "Search knowledge sources"),
            AgentDefinition("resolution_supervisor", "Synthesize findings and coordinate draft"),
            AgentDefinition("draft_writer", "Write customer-facing draft response"),
            AgentDefinition("compliance_reviewer", "Review draft against policy"),
            AgentDefinition("ticket_update", "Write external ticket updates"),
        ]