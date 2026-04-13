from __future__ import annotations

from pathlib import Path
from typing import Any

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.catalog import build_default_agent_definitions
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT, KNOWLEDGE_RETRIEVER_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
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
        runtime_harness_manager: RuntimeHarnessManager | None = None,
    ):
        self._config = config
        self._instruction_loader = instruction_loader
        self._tool_registry = tool_registry
        self._memory_store = memory_store
        self._runtime_harness_manager = runtime_harness_manager

    def build_agent(self, case_id: str, definition: AgentDefinition) -> Any:
        role = definition.role
        agent_settings = self.get_agent_settings(role)
        # Runtime constraint: resolved here once and then reused for instruction loading and agent execution.
        constraint_mode = (
            self._runtime_harness_manager.resolve(role)
            if self._runtime_harness_manager is not None
            else self._config.agents.resolve_constraint_mode(role)
        )
        system_prompt = self._instruction_loader.load(case_id, role, constraint_mode=constraint_mode)
        tools = self._tool_registry.get_tools(role)
        model_name = agent_settings.model if agent_settings is not None else None
        selected_model = model_name or self._config.llm.model
        backend = self._build_backend_for_role(role)

        if create_deep_agent is None:
            raise RuntimeError("DeepAgents is unavailable because the deepagents package could not be imported.")

        create_kwargs: dict[str, Any] = {
            "tools": [tool.handler for tool in tools],
            "system_prompt": system_prompt,
            "model": selected_model,
        }
        if backend is not None:
            create_kwargs["backend"] = backend
        try:
            return create_deep_agent(**create_kwargs)
        except Exception as exc:
            raise RuntimeError(f"DeepAgents agent initialization failed for role '{role}'.") from exc

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