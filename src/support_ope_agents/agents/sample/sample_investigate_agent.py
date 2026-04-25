from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.tools.builtin_tools import build_builtin_tools
from support_ope_agents.tools.case_memory_manager import CaseMemoryManager
from support_ope_agents.util.document import build_filtered_document_source_backend
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model
from ...tools.registry import ToolRegistry
from ...instructions.investigate_system_prompt import INVESTIGATE_SYSTEM_PROMPT_TEMPLATE
from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent



class SampleInvestigateAgent(AbstractAgent):
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

    @staticmethod
    def _is_contradictory_document_summary(document_summary: str, log_path: Path | None) -> bool:
        if log_path is None:
            return False
        normalized = document_summary.strip().lower()
        if not normalized:
            return False
        missing_markers = (
            "見つから",
            "存在しない",
            "存在していない",
            "不足している",
            "アップロードされていない",
            "再提供",
            "not found",
            "missing",
            "does not exist",
        )
        return log_path.name.lower() in normalized and any(marker in normalized for marker in missing_markers)


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
        route_base: str = "docs"
    ) -> Any:
        backend = build_filtered_document_source_backend(
            document_sources=document_sources,
            route_base=route_base,
        )
        tools = {t.name: t.handler for t in self.tool_registry.get_tools(INVESTIGATE_AGENT)}
        system_prompt = self._build_system_prompt(query, instruction_text)
        model = build_chat_openai_model(self.config)
        return create_deep_agent(
            model=model,
            backend=backend,
            system_prompt=system_prompt,
            tools=[t for t in tools.values() if t],
            name="investigate-sample",
        )

    def create_node(self) -> Any:
        return self.create_sub_agent(query=self._default_query())

    def execute(
        self,
        *,
        query: str,
        workspace_path: str | None = None,
        instruction_text: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> Any:
        effective_query = query.strip() or self._default_query()
        log_path_value = str((state or {}).get("investigation_evidence_log_path") or "").strip()
        log_path = Path(log_path_value) if log_path_value else None
        investigation_query = effective_query

        try:
            sub_agent = self.create_sub_agent(query=investigation_query, instruction_text=instruction_text or "")
            result = sub_agent.invoke(
                {
                    "messages": [
                        HumanMessage(content=investigation_query),
                    ]
                }
            )
        except Exception:
            if log_path is not None:
                return f"Evidence file: {log_path.name}\nEvidence path: {log_path}"
            raise

        document_summary = extract_result_output_text(result)
        if not document_summary and isinstance(result, dict):
            document_summary = str(result.get("output") or "")
        if not document_summary:
            document_summary = format_result(result)
        if self._is_contradictory_document_summary(document_summary, log_path):
            document_summary = ""
        if not document_summary and log_path is not None:
            return ""
        return result

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