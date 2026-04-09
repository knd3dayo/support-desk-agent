from __future__ import annotations

from typing import Any

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.catalog import build_default_agent_definitions
from support_ope_agents.agents.roles import candidate_role_names, canonical_role
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools import ToolRegistry

try:
    from deepagents import create_deep_agent
except Exception:  # pragma: no cover
    create_deep_agent = None
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
        agent_settings = self.get_agent_settings(role)
        model_name = agent_settings.model if agent_settings is not None else None
        selected_model = model_name or self._config.llm.model

        if create_deep_agent is None:
            return {
                "role": role,
                "description": definition.description,
                "kind": definition.kind,
                "parent_role": definition.parent_role,
                "system_prompt": system_prompt,
                "tools": [
                    {
                        "name": tool.name,
                        "provider": tool.provider,
                        "target": tool.target,
                    }
                    for tool in tools
                ],
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
                "tools": [
                    {
                        "name": tool.name,
                        "provider": tool.provider,
                        "target": tool.target,
                    }
                    for tool in tools
                ],
                "runtime_warning": str(exc),
            }

    def build_default_definitions(self) -> list[AgentDefinition]:
        return build_default_agent_definitions()

    def get_agent_settings(self, role: str):
        for candidate in candidate_role_names(role):
            settings = self._config.agents.get(candidate)
            if settings is not None:
                return settings
        return None