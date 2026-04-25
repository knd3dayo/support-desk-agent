from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import BACK_SUPPORT_ESCALATION_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.deep_agents_extension import FilteredFilesystemBackend

from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.instructions.back_support_escalation_system_prompt import SYSTEM_PROMPT
from support_ope_agents.instructions.back_support_escalation_user_prompt import USER_PROMPT_TEMPLATE
from support_ope_agents.tools.registry import ToolRegistry


class SampleBackSupportEscalationResponse(BaseModel):
    escalation_reason: str = Field(default="調査結果だけでは確実な回答が困難")
    escalation_summary: str = Field(default="")
    inquiry_draft: str = Field(default="")
    required_log_files: list[str] = Field(default_factory=list)
    attachment_candidates: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)



class SampleBackSupportEscalationAgent(AbstractAgent):
    def __init__(self, config: Any, memory_dir: str):
        from support_ope_agents.tools.registry import ToolRegistry
        self.config = config
        self.tool_registry = ToolRegistry(config)
        self.memory_dir = memory_dir

    @staticmethod
    def _default_memory_dir() -> str:
        return "samples/support-ope-agents/work/CASE-20260416-013703-2ADB/.memory"

    @staticmethod
    def _default_query() -> str:
        return "バックサポート向け問い合わせ文を作成し、連携が必要なログや追加資料を整理してください。"

    def _build_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _build_user_prompt(self, query: str) -> str:
        return USER_PROMPT_TEMPLATE.format(query=query)

    def create_sub_agent(self, *, query: str | None = None) -> Any:
        memory_root = Path(self.memory_dir).expanduser().resolve()
        if not memory_root.exists() or not memory_root.is_dir():
            raise RuntimeError(f"Memory directory does not exist: {memory_root}")
        backend = FilteredFilesystemBackend(
            root_dir=memory_root,
            virtual_mode=True,
            ignore_patterns=("**/__pycache__/**", "**/.DS_Store"),
        )
        # 必要なツールがあればToolRegistryから取得してtoolsに追加
        # get_toolsはToolRegistryのpublicメソッド
        tools = {t.name: t.handler for t in self.tool_registry.get_tools(BACK_SUPPORT_ESCALATION_AGENT)}
        # ToolRegistry._configはprivate属性なので、コンストラクタでAppConfigを保持しておく
        # _configはprivate属性なので、self._config(AppConfig)を使う
        model = build_chat_openai_model(self.config)
        return create_deep_agent(
            model=model,
            backend=backend,
            system_prompt=self._build_system_prompt(),
            response_format=SampleBackSupportEscalationResponse,
            tools=[t for t in tools.values() if t],
            name="back-support-escalation-sample",
        )

    def create_node(self) -> Any:
        return self.create_sub_agent(query=self._default_query())

    def execute(self, *, query: str | None = None) -> dict[str, Any]:
        agent = self.create_sub_agent(query=query)
        result = agent.invoke(
            {
                "messages": [
                    HumanMessage(content=self._build_user_prompt((query or self._default_query()).strip())),
                ]
            }
        )
        if not isinstance(result, dict):
            raise ValueError("SampleBackSupportEscalationAgent returned a non-dict payload.")

        structured = result.get("structured_response")
        if isinstance(structured, SampleBackSupportEscalationResponse):
            payload = structured.model_dump()
        elif isinstance(structured, dict):
            payload = SampleBackSupportEscalationResponse.model_validate(structured).model_dump()
        else:
            raise ValueError("SampleBackSupportEscalationAgent did not return a structured response.")

        return {
            "escalation_required": True,
            "escalation_reason": payload["escalation_reason"],
            "escalation_summary": payload["escalation_summary"],
            "escalation_draft": payload["inquiry_draft"],
            "escalation_missing_artifacts": payload["required_log_files"],
            "escalation_attachment_candidates": payload["attachment_candidates"],
            "escalation_evidence_paths": payload["evidence_paths"],
            "current_agent": BACK_SUPPORT_ESCALATION_AGENT,
        }

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            BACK_SUPPORT_ESCALATION_AGENT,
            "Organize evidence and draft a back support escalation inquiry from case memory",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_back_support_escalation_agent_definition() -> AgentDefinition:
        return SampleBackSupportEscalationAgent.build_agent_definition()



def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample back support escalation agent")
    parser.add_argument("query", nargs="?", default=SampleBackSupportEscalationAgent._default_query(), help="Escalation preparation request")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    parser.add_argument(
        "--memory-dir",
        default=SampleBackSupportEscalationAgent._default_memory_dir(),
        help="Path to the case .memory directory",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    tool_registry = ToolRegistry(config)
    agent = SampleBackSupportEscalationAgent(config=config, memory_dir=args.memory_dir)
    result = agent.execute(query=args.query)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())