from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence, cast

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig, KnowledgeDocumentSource
from support_ope_agents.models.state import CaseState
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.tools.builtin_tools import build_builtin_tools
from support_ope_agents.tools.case_memory_manager import CaseMemoryManager
from support_ope_agents.util.asyncio_utils import run_awaitable_sync
from support_ope_agents.util.document import build_filtered_document_source_backend
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model, create_deep_agent_compatible_agent, wrap_tool_handler_sync
from support_ope_agents.util.workspace_evidence import build_workspace_evidence_source, find_evidence_log_file
from ...tools.registry import ToolRegistry
from ...instructions.investigate_system_prompt import INVESTIGATE_SYSTEM_PROMPT_TEMPLATE
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph




class SampleInvestigateAgent(AbstractAgent):
    @staticmethod
    def _agent_memory_sources() -> list[str]:
        agents_memory_path = Path(__file__).resolve().parents[2] / "AGENTS.md"
        if not agents_memory_path.exists():
            return []
        return [str(agents_memory_path)]

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.tool_registry = ToolRegistry(config)

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    def _build_system_prompt(self, query: str, instruction_text: str = "") -> str:
        prompt = INVESTIGATE_SYSTEM_PROMPT_TEMPLATE.format(query=query)
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
        document_sources: Sequence[Any] = (),
        route_base: str = "docs",
        workspace_path: str | None = None,
    ) -> CompiledStateGraph:
        effective_document_sources = list(document_sources) if document_sources else self._resolve_document_sources(workspace_path)
        backend = build_filtered_document_source_backend(
            document_sources=effective_document_sources,
            route_base=route_base,
        )
        tools = {t.name: wrap_tool_handler_sync(t.handler) for t in self.tool_registry.get_tools(INVESTIGATE_AGENT)}
        system_prompt = self._build_system_prompt(query, instruction_text)
        model = build_chat_openai_model(self.config)
        memory_sources = self._agent_memory_sources()
        # Avoid create_deep_agent here because it auto-injects middleware such as
        # summarization and provider-specific prompt caching. Those defaults were
        # the source of residual warning/resourcewarning behavior in standalone runs.
        # Rebuild only the middleware we need through the shared create_agent-based
        # wrapper so other agents can reuse the same controlled setup.
        return cast(
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
        return run_awaitable_sync(runnable.ainvoke(payload, context=context))

    def execute(
        self,
        *,
        query: str,
        workspace_path: str | None = None,
        instruction_text: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> Any:
        effective_query = query.strip() or self._default_query()
        sub_agent = self.create_sub_agent(
            query=effective_query,
            instruction_text=instruction_text or "",
            workspace_path=workspace_path,
        )
        context = self._build_context(workspace_path=workspace_path, state=state)
        return self._invoke_sub_agent(
            sub_agent,
            {
                "messages": [
                    HumanMessage(content=effective_query),
                ]
            },
            context=context,
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