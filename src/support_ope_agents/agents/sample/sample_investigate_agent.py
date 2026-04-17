from __future__ import annotations

import argparse
from typing import Any
from dataclasses import dataclass

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
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

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    def _build_system_prompt(self, query: str) -> str:
        return (
            """
            あなたはサポートケースの調査担当エージェントです。
            ケースの内容に基づいて、関連するログやドキュメントを調査し、サポート担当者が問題を理解しやすいように要約してください。
            調査の結果、サポート担当者が次に取るべきアクションも提案してください。
            検索でヒットした箇所は、ヒット行だけで判断せず、必ずその前後10行以上を read_file で確認して文脈を把握してください。
            grep や検索結果に line 情報が含まれる場合は、その近傍を優先して読んでください。
            README や Markdown、設定ファイル内にリンク、参照先 path、関連ファイル名が出てきた場合は、そのリンク先や参照先ファイルも追加で調査してください。
            ただし、README に書かれている外部 path や参照先が現在の backend 内に存在しない場合、その path の内容を読んだ前提で説明してはいけません。
            backend 外の参照先は「今回の調査 backend からは未到達」とみなし、現在読める backend 内の別ソース、別ファイル、別の一致箇所を探してください。
            参照先が未到達なら、その README 自体は補助情報にとどめ、対象そのものを直接説明している一次情報が backend 内にあるかを再探索してください。
            特に「〜について教えて」のような説明要求では、サンプル説明文ではなく、対象そのものを説明している一次情報を優先してください。
            調査根拠は1ファイルだけで確定せず、少なくとも複数の関連箇所を確認してから結論を出してください。
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


def _extract_result_output(result: Any) -> str:
    return extract_result_output_text(result) or format_result(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample investigate deep agent")
    parser.add_argument("query", nargs="?", default=SampleInvestigateAgent._default_query(), help="Investigation query")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    args = parser.parse_args()

    config = load_config(args.config)
    agent = SampleInvestigateAgent(config)
    result = agent.execute(query=args.query)
    print(_extract_result_output(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())