from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence, cast

from support_desk_agent.agents.abstract_agent import AbstractAgent
from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_desk_agent.config.loader import load_config
from support_desk_agent.config.models import AppConfig, KnowledgeDocumentSource
from support_desk_agent.models.state import CaseState
from support_desk_agent.runtime.conversation_messages import extract_result_output_text
from support_desk_agent.util.document import build_filtered_document_source_backend
from support_desk_agent.util.formatting import format_result
from support_desk_agent.util.langchain import build_chat_openai_model, create_deep_agent_compatible_agent, wrap_tool_handler_sync
from support_desk_agent.util.langchain.chat_model import close_chat_openai_model
from support_desk_agent.workspace import build_workspace_evidence_source
from ...tools.registry import ToolRegistry
from ...instructions.investigate_system_prompt import INVESTIGATE_SYSTEM_PROMPT_TEMPLATE
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph




class SampleInvestigateAgent(AbstractAgent):
    PLAN_MODE = "plan"
    ACTION_MODE = "action"
    _LOG_RANGE_HINT_MARKERS = (
        "incident timeframe:",
        "requested extract range:",
        "extract_log_time_range",
    )

    @staticmethod
    def _agent_memory_sources() -> list[str]:
        package_agents_memory_path = Path(__file__).resolve().parents[2] / "AGENTS.md"
        if package_agents_memory_path.exists():
            return [str(package_agents_memory_path)]
        repository_agents_memory_path = Path(__file__).resolve().parents[4] / "AGENTS.md"
        if repository_agents_memory_path.exists():
            return [str(repository_agents_memory_path)]
        return []

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.tool_registry = ToolRegistry(config)

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    @classmethod
    def _should_enable_log_range_tools(cls, query: str) -> bool:
        normalized_query = query.lower()
        return any(marker in normalized_query for marker in cls._LOG_RANGE_HINT_MARKERS)

    def _build_system_prompt(self, query: str, instruction_text: str = "", mode: str = ACTION_MODE) -> str:
        prompt = INVESTIGATE_SYSTEM_PROMPT_TEMPLATE.format(query=query)
        if mode == self.PLAN_MODE:
            mode_instruction = (
                "現在は計画策定フェーズです。調査を実行せず、"
                "必要な確認順序、使うべき根拠、未解決論点を整理した計画だけを返してください。"
                "出力は必ず日本語で、計画要約・主要ステップ・未解決論点・次アクションの順で整理してください。"
            )
        else:
            mode_instruction = (
                "現在は調査実行フェーズです。与えられた計画と followup notes を踏まえ、"
                "必要な調査を実行して結果を返してください。"
                "出力は必ず日本語で、少なくとも『結論』『根拠』『原因候補』『次アクション』の4見出しを含めてください。"
                "根拠では、実際に確認したログ断片・ファイル名・設定名を具体的に示してください。"
                "Supervisor から existence 確認済みの evidence preview が与えられている場合、そのファイルが見つからないとは書かず、"
                "preview に含まれる内容を一次情報として扱ってください。"
                "Supervisor が明示した添付 path 以外のファイルパスを推測して使ってはいけません。"
                "添付 path に .zip が明示されていない限り、list_zip_contents や extract_zip を呼び出してはいけません。"
                "英語だけの回答は禁止です。日本語で完結にまとめ、サポート担当者がそのまま使える文面にしてください。"
            )
        prompt = f"{prompt}\n\n実行モード: {mode}\n{mode_instruction}"
        instruction = instruction_text.strip()
        if instruction:
            prompt = f"{prompt}\n\n追加 instruction:\n{instruction}"
        return prompt

    def _resolve_document_sources(self, workspace_path: str | None) -> list[KnowledgeDocumentSource]:
        sources = list(self.config.agents.InvestigateAgent.document_sources)
        evidence_source = build_workspace_evidence_source(
            workspace_path,
            evidence_subdir=self.config.data_paths.evidence_subdir,
        )
        if evidence_source is not None:
            sources.append(evidence_source)
        return sources


    def read_investigate_working_memory(self, case_id: str, workspace_path: str) -> str:
        """
        ToolRegistryの共通APIでworking memory contentを取得
        """
        return self.tool_registry.read_investigate_working_memory_for_case(case_id, workspace_path, role=INVESTIGATE_AGENT)

    def create_sub_agent(
        self,
        query: str,
        instruction_text: str = "",
        mode: str = ACTION_MODE,
        document_sources: Sequence[Any] = (),
        route_base: str = "docs",
        workspace_path: str | None = None,
    ) -> CompiledStateGraph:
        effective_document_sources = list(document_sources) if document_sources else self._resolve_document_sources(workspace_path)
        backend = build_filtered_document_source_backend(
            document_sources=effective_document_sources,
            route_base=route_base,
        )
        enabled_tool_names = None
        if not self._should_enable_log_range_tools(query):
            enabled_tool_names = {"extract_log_time_range"}
        tools = {
            t.name: wrap_tool_handler_sync(t.handler)
            for t in self.tool_registry.get_tools(INVESTIGATE_AGENT)
            if enabled_tool_names is None or t.name not in enabled_tool_names
        }
        system_prompt = self._build_system_prompt(query, instruction_text, mode=mode)
        model = build_chat_openai_model(self.config)
        memory_sources = self._agent_memory_sources()
        # Avoid create_deep_agent here because it auto-injects middleware such as
        # summarization and provider-specific prompt caching. Those defaults were
        # the source of residual warning/resourcewarning behavior in standalone runs.
        # Rebuild only the middleware we need through the shared create_agent-based
        # wrapper so other agents can reuse the same controlled setup.
        compiled_agent = cast(
            CompiledStateGraph,
            create_deep_agent_compatible_agent(
                model=model,
                backend=backend,
                system_prompt=system_prompt,
                tools=[t for t in tools.values() if t],
                memory=memory_sources or None,
                context_schema=CaseState,
                name="investigate-sample",
            ),
        )
        try:
            setattr(compiled_agent, "_support_ope_chat_model", model)
        except AttributeError:
            pass
        return compiled_agent

    def create_node(self) -> CompiledStateGraph:
        return self.create_sub_agent(query=self._default_query())

    @staticmethod
    def _build_context(*, workspace_path: str | None, state: dict[str, Any] | None) -> CaseState:
        context = cast(CaseState, dict(state or {}))
        if workspace_path and not str(context.get("workspace_path") or "").strip():
            context["workspace_path"] = workspace_path
        return context

    @staticmethod
    def _invoke_sub_agent(sub_agent: CompiledStateGraph, payload: dict[str, Any], *, context: CaseState) -> Any:
        runnable = cast(Any, sub_agent)
        if hasattr(runnable, "ainvoke") and not hasattr(runnable, "invoke"):
            import asyncio

            return asyncio.run(runnable.ainvoke(payload, context=context))
        return runnable.invoke(payload, context=context)

    def execute(
        self,
        *,
        query: str,
        mode: str = ACTION_MODE,
        workspace_path: str | None = None,
        instruction_text: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> Any:
        effective_query = query.strip() or self._default_query()
        sub_agent = self.create_sub_agent(
            query=effective_query,
            instruction_text=instruction_text or "",
            mode=mode,
            workspace_path=workspace_path,
        )
        context = self._build_context(workspace_path=workspace_path, state=state)
        context["execution_mode"] = cast(Any, mode)
        model = getattr(sub_agent, "_support_ope_chat_model", None)
        try:
            return self._invoke_sub_agent(
                sub_agent,
                {
                    "messages": [
                        HumanMessage(content=effective_query),
                    ]
                },
                context=context,
            )
        finally:
            if model is not None:
                close_chat_openai_model(model)

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
    parser = argparse.ArgumentParser(description="Run the sample investigate agent")
    parser.add_argument("query", nargs="?", default=SampleInvestigateAgent._default_query(), help="Investigation query")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    parser.add_argument("--workspace-path", default=None, help="Path to workspace directory")
    args = parser.parse_args()

    config = load_config(args.config)
    agent = SampleInvestigateAgent(config)
    result = agent.execute(query=args.query, workspace_path=args.workspace_path)
    print(_extract_result_output(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())