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


class SampleBackSupportEscalationResponse(BaseModel):
    escalation_reason: str = Field(default="調査結果だけでは確実な回答が困難")
    escalation_summary: str = Field(default="")
    inquiry_draft: str = Field(default="")
    required_log_files: list[str] = Field(default_factory=list)
    attachment_candidates: list[str] = Field(default_factory=list)
    evidence_paths: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class SampleBackSupportEscalationAgent(AbstractAgent):
    config: AppConfig
    memory_dir: str

    @staticmethod
    def _default_memory_dir() -> str:
        return "samples/ai-platform-poc/work/CASE-20260416-013703-2ADB/.memory"

    @staticmethod
    def _default_query() -> str:
        return "バックサポート向け問い合わせ文を作成し、連携が必要なログや追加資料を整理してください。"

    def _build_system_prompt(self) -> str:
        return (
            "あなたはバックサポートへのエスカレーション準備担当です。\n"
            "与えられた filesystem backend には 1 ケース分の .memory 記録がマウントされています。\n"
            "shared 配下の共有記録と agents 配下の各 agent 作業記録だけを根拠にしてください。\n"
            "作業開始時に必ず ls('/')、ls('/shared')、ls('/agents') を実行して、backend が見えていることを確認してください。\n"
            "少なくとも /shared/context.md と /shared/progress.md を読み、必要に応じて /shared/summary.md と /agents/*/working.md を参照してください。\n"
            "filesystem tools を使って必要なファイルを調べ、問い合わせ文案と不足資料を structured output で返してください。\n"
            "ファイル編集やコマンド実行は行わないでください。\n"
            "backend を確認していない段階で『記録がない』と判断してはいけません。\n"
            "事実を捏造せず、記録にないものは不足資料として整理してください。"
        )

    def _build_user_prompt(self, query: str) -> str:
        return (
            "目的:\n"
            "- バックサポートへ渡す問い合わせ文案を日本語で作成する\n"
            "- 連携すべきログ、再現情報、添付候補ファイルを整理する\n"
            "- shared と agents の両方を確認し、根拠に使った path を evidence_paths に入れる\n"
            "- required_log_files には不足しているが収集依頼すべきログや再現情報を入れる\n"
            "- attachment_candidates には既に memory 配下に存在し、問い合わせに添付すべき path を入れる\n"
            "- inquiry_draft は、そのままバックサポートに渡せる文面にする\n"
            "- evidence_paths には実際に読んだ backend path を必ず 2 件以上入れる\n"
            f"依頼内容:\n{query}"
        )

    def create_sub_agent(self, *, query: str | None = None) -> Any:
        memory_root = Path(self.memory_dir).expanduser().resolve()
        if not memory_root.exists() or not memory_root.is_dir():
            raise RuntimeError(f"Memory directory does not exist: {memory_root}")

        backend = FilteredFilesystemBackend(
            root_dir=memory_root,
            virtual_mode=True,
            ignore_patterns=("**/__pycache__/**", "**/.DS_Store"),
        )
        return create_deep_agent(
            model=build_chat_openai_model(self.config),
            backend=backend,
            system_prompt=self._build_system_prompt(),
            response_format=SampleBackSupportEscalationResponse,
            tools=[],
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
    agent = SampleBackSupportEscalationAgent(config=config, memory_dir=args.memory_dir)
    result = agent.execute(query=args.query)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())