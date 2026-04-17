from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from ..util.document.document_source_backend import build_document_source_backend

from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from support_ope_agents.config.models import AppConfig

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

    def _get_chat_model(self) -> ChatOpenAI:
        if not self.config.llm.api_key:
            raise ValueError("LLM API key is not configured")
        return ChatOpenAI(
            model=self.config.llm.model,
            api_key=self.config.llm.api_key, # type: ignore
            base_url=self.config.llm.base_url,
        )

    def create_node(self) -> Any:

        settings = self.config.agents.InvestigateAgent
        query = "調査すべき内容をここに記載してください"  #

        backend = build_document_source_backend(document_sources=settings.document_sources, route_base="knowledge")
        if backend is None:
            raise RuntimeError(
                "Knowledge document backend could not be initialized. Check agents.InvestigateAgent.document_sources."
            )
        
        agent = create_deep_agent(
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
            ).format(query=query),  
            tools=[],
            name="investigate-agent",
        )
        return agent

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