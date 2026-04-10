from __future__ import annotations

from pathlib import Path
from typing import Any

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.catalog import build_default_agent_definitions
from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools import ToolRegistry

try:
    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
except Exception:  # pragma: no cover
    create_deep_agent = None
    CompositeBackend = None
    FilesystemBackend = None
    StateBackend = None


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
        role = definition.role
        system_prompt = self._instruction_loader.load(case_id, role)
        tools = self._tool_registry.get_tools(role)
        agent_settings = self.get_agent_settings(role)
        model_name = agent_settings.model if agent_settings is not None else None
        selected_model = model_name or self._config.llm.model
        backend = self._build_backend_for_role(role)

        if create_deep_agent is None:
            payload: dict[str, Any] = {
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
            if backend is not None:
                payload["backend"] = self._describe_backend_for_role(role)
            return payload

        try:
            create_kwargs: dict[str, Any] = {
                "tools": [tool.handler for tool in tools],
                "system_prompt": system_prompt,
                "model": selected_model,
            }
            if backend is not None:
                create_kwargs["backend"] = backend
            return create_deep_agent(**create_kwargs)
        except Exception as exc:
            payload = {
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
            if backend is not None:
                payload["backend"] = self._describe_backend_for_role(role)
            return payload

    def _build_backend_for_role(self, role: str) -> Any | None:
        if role != KNOWLEDGE_RETRIEVER_AGENT:
            return None
        if CompositeBackend is None or FilesystemBackend is None or StateBackend is None:
            return None

        routes: dict[str, Any] = {}
        for source in self._config.knowledge_retrieval.document_sources:
            source_path = Path(source.path).expanduser().resolve()
            route_prefix = f"/knowledge/{source.name}/"
            routes[route_prefix] = FilesystemBackend(root_dir=str(source_path), virtual_mode=True)

        if not routes:
            return None

        return CompositeBackend(
            default=StateBackend(),
            routes=routes,
        )

    def _describe_backend_for_role(self, role: str) -> dict[str, Any] | None:
        if role != KNOWLEDGE_RETRIEVER_AGENT:
            return None
        document_sources = self._config.knowledge_retrieval.document_sources
        if not document_sources:
            return None
        return {
            "type": "CompositeBackend",
            "default": "StateBackend",
            "routes": {
                f"/knowledge/{source.name}/": str(Path(source.path).expanduser().resolve())
                for source in document_sources
            },
        }

    def build_default_definitions(self) -> list[AgentDefinition]:
        return build_default_agent_definitions()

    def get_agent_settings(self, role: str):
        return self._config.agents.get(role)