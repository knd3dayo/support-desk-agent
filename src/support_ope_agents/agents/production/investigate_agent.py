from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping, cast

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.config.models import AppConfig, KnowledgeDocumentSource
from support_ope_agents.util.formatting import format_result
from ...util.document.document_source_backend import build_document_source_backend

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from deepagents import create_deep_agent

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class InvestigateAgent(AbstractAgent):
    """
    InvestigateAgentはケースの調査を担当するエージェントで、
    ログ分析、知識取得、調査結果の要約、共有メモリへの書き込みなどの機能を提供します。
    create_node() で Investigate フェーズの実装をLanggraph のDeepAgentノードとして提供します。

    """
    config: AppConfig
    read_shared_memory_tool: Callable[..., Any] | None = None
    write_shared_memory_tool: Callable[..., Any] | None = None

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    def _get_chat_model(self) -> ChatOpenAI:
        if not self.config.llm.api_key:
            raise ValueError("LLM API key is not configured")
        return ChatOpenAI(
            model=self.config.llm.model,
            api_key=self.config.llm.api_key, # type: ignore
            base_url=self.config.llm.base_url,
        )

    def create_sub_agent(self, *, query: str | None = None) -> Any:
        settings = self.config.agents.InvestigateAgent
        effective_query = (query or self._default_query()).strip()

        backend = build_document_source_backend(document_sources=settings.document_sources, route_base="knowledge")
        if backend is None:
            raise RuntimeError(
                "Knowledge document backend could not be initialized. Check agents.InvestigateAgent.document_sources."
            )

        return create_deep_agent(
            model=self._get_chat_model(),
            backend=backend,
            system_prompt=(
                """
                あなたはサポートケースの調査担当エージェントです。
                ケースの内容に基づいて、関連するログやドキュメントを調査し、サポート担当者が問題を理解しやすいように要約してください。
                調査の結果、サポート担当者が次に取るべきアクションも提案してください。
                調査対象のクエリ:
                {query}
                """
            ).format(query=effective_query),
            tools=[],
            name="investigate-agent",
        )

    def create_node(self) -> Any:
        return self.create_sub_agent(query=self._default_query())

    def execute(self, state: Mapping[str, Any]) -> dict[str, Any]:
        update = dict(state)
        query = str(update.get("raw_issue") or "").strip() or self._default_query()
        result = self.create_sub_agent(query=query).invoke({"messages": [HumanMessage(content=query)]})
        update["current_agent"] = INVESTIGATE_AGENT
        update["investigation_summary"] = format_result(result)
        update.setdefault("log_analysis_summary", "")
        update.setdefault("log_analysis_file", "")
        update.setdefault("knowledge_retrieval_summary", "")
        update.setdefault("knowledge_retrieval_results", [])
        update.setdefault("knowledge_retrieval_adopted_sources", [])
        update.setdefault("knowledge_retrieval_final_adopted_source", "")
        return update

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            INVESTIGATE_AGENT,
            "Investigate the case, gather evidence, and prepare a support-facing draft",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_investigate_agent_definition() -> AgentDefinition:
        return InvestigateAgent.build_agent_definition()