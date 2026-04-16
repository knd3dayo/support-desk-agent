from __future__ import annotations

import argparse
from typing import Any
from dataclasses import dataclass

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.document import build_filtered_document_source_backend
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent

@dataclass(slots=True)
class SampleInvestigateAgent(AbstractAgent):
    """
    InvestigateAgentはケースの調査を担当するエージェントで、
    ログ分析、知識取得、調査結果の要約、共有メモリへの書き込みなどの機能を提供します。
    create_node() で Investigate フェーズの実装をLanggraph のDeepAgentノードとして提供します。

    """
    config: AppConfig

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    def _build_system_prompt(self, query: str) -> str:
        return (
            """
            あなたはサポートケースの調査担当エージェントです。
            ケースの内容に基づいて、関連するログやドキュメントを調査し、サポート担当者が問題を理解しやすいように要約してください。
            調査の結果、サポート担当者が次に取るべきアクションも提案してください。
            調査対象のクエリ:
            {query}
            """
        ).format(query=query)

    def create_sub_agent(self, *, query: str | None = None) -> Any:
        settings = self.config.agents.InvestigateAgent
        effective_query = (query or self._default_query()).strip()

        backend = build_filtered_document_source_backend(
            document_sources=settings.document_sources,
            route_base="knowledge",
        )
        if backend is None:
            raise RuntimeError(
                "Knowledge document backend could not be initialized. Check agents.InvestigateAgent.document_sources."
            )

        agent = create_deep_agent(
            model=build_chat_openai_model(self.config),
            backend=backend,
            system_prompt=self._build_system_prompt(effective_query),
            tools=[],
            name="investigate-agent",
        )
        return agent

    def create_node(self) -> Any:
        return self.create_sub_agent(query=self._default_query())

    def execute(self, *, query: str) -> Any:
        sub_agent = self.create_sub_agent(query=query)
        return sub_agent.invoke(
            {
                "messages": [
                    HumanMessage(content=query),
                ]
            }
        )

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
        return SampleInvestigateAgent.build_agent_definition()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample investigate deep agent")
    parser.add_argument("query", nargs="?", default=SampleInvestigateAgent._default_query(), help="Investigation query")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    args = parser.parse_args()

    config = load_config(args.config)
    agent = SampleInvestigateAgent(config=config)
    result = agent.execute(query=args.query)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())