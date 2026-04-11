from __future__ import annotations

from pathlib import Path
from typing import Any

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.catalog import build_default_agent_definitions
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT, KNOWLEDGE_RETRIEVER_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools import ToolRegistry
from support_ope_agents.tools.document_source_backend import build_document_source_backend, describe_document_source_backend

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
        if role not in {KNOWLEDGE_RETRIEVER_AGENT, COMPLIANCE_REVIEWER_AGENT}:
            return None
        route_base = "knowledge" if role == KNOWLEDGE_RETRIEVER_AGENT else "policy"
        settings = (
            self._config.agents.KnowledgeRetrieverAgent
            if role == KNOWLEDGE_RETRIEVER_AGENT
            else self._config.agents.ComplianceReviewerAgent
        )
        return build_document_source_backend(
            document_sources=settings.document_sources,
            route_base=route_base,
        )

    def _describe_backend_for_role(self, role: str) -> dict[str, Any] | None:
        if role not in {KNOWLEDGE_RETRIEVER_AGENT, COMPLIANCE_REVIEWER_AGENT}:
            return None
        route_base = "knowledge" if role == KNOWLEDGE_RETRIEVER_AGENT else "policy"
        document_sources = (
            self._config.agents.KnowledgeRetrieverAgent.document_sources
            if role == KNOWLEDGE_RETRIEVER_AGENT
            else self._config.agents.ComplianceReviewerAgent.document_sources
        )
        return describe_document_source_backend(document_sources=document_sources, route_base=route_base)

    def build_default_definitions(self) -> list[AgentDefinition]:
        return build_default_agent_definitions()

    def get_agent_settings(self, role: str):
        return self._config.agents.get(role)