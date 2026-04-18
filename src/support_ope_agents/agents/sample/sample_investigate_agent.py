from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.tools.builtin_tools import _detect_log_format_from_lines
from support_ope_agents.tools.builtin_tools import _extract_text_from_path
from support_ope_agents.tools.builtin_tools import _search_log_with_patterns
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

    @staticmethod
    def _find_evidence_log_file(workspace_path: str) -> Path | None:
        workspace_root = Path(workspace_path).expanduser().resolve()
        candidate_dirs = [workspace_root / ".evidence", workspace_root / "evidence"]
        preferred_names = ["application.log", "vdp.log"]
        for directory in candidate_dirs:
            if not directory.exists():
                continue
            for name in preferred_names:
                candidate = directory / name
                if candidate.exists() and candidate.is_file():
                    return candidate
            discovered_files = [path for path in sorted(directory.rglob("*")) if path.is_file()]
            for path in discovered_files:
                if path.suffix.lower() == ".log":
                    return path
            for path in discovered_files:
                if path.suffix.lower() in {".out", ".txt"}:
                    return path
        return None

    @staticmethod
    def _trim_line(line: str, *, limit: int = 180) -> str:
        compact = " ".join(line.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3] + "..."

    @classmethod
    def _summarize_workspace_log(cls, workspace_path: str | None) -> str:
        if not workspace_path:
            return ""
        log_path = cls._find_evidence_log_file(workspace_path)
        if log_path is None:
            return ""
        text = _extract_text_from_path(log_path)
        lines = text.splitlines()
        if not lines:
            return f"{log_path.name} は添付されていましたが、内容は空でした。"

        detection = _detect_log_format_from_lines(lines[:100])
        search_results = _search_log_with_patterns(
            text,
            generated_patterns=detection["generated_patterns"],
            search_terms=[],
            match_limit=20,
        )
        severity_entries = search_results.get("severity") or []
        exception_entries = search_results.get("java_exception") or []

        parts = [
            f"{log_path.name} を解析し、形式は {detection['primary_format']} と判定しました。",
            f"severity 一致 {len(severity_entries)} 件、例外一致 {len(exception_entries)} 件。",
        ]

        if severity_entries:
            first_severity = severity_entries[0]
            if isinstance(first_severity, dict):
                line_number = first_severity.get("line_number")
                line = cls._trim_line(str(first_severity.get("line") or ""))
                if line:
                    parts.append(f"代表的な異常行: L{line_number}: {line}。")

        if exception_entries:
            first_exception = exception_entries[0]
            if isinstance(first_exception, dict):
                line = cls._trim_line(str(first_exception.get("line") or ""))
                if line:
                    parts.append(f"例外候補: {line}。")
        elif not severity_entries:
            parts.append(f"先頭行: {cls._trim_line(lines[0])}。")

        return "".join(parts)

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

    def execute(self, *, query: str, workspace_path: str | None = None) -> Any:
        effective_query = query.strip() or self._default_query()
        log_summary = self._summarize_workspace_log(workspace_path)

        try:
            sub_agent = self.create_sub_agent(query=effective_query)
            result = sub_agent.invoke(
                {
                    "messages": [
                        HumanMessage(content=effective_query),
                    ]
                }
            )
        except Exception:
            if log_summary:
                return log_summary
            raise

        document_summary = extract_result_output_text(result) or format_result(result)
        if log_summary and document_summary:
            return f"{log_summary}\n\n補足情報:\n{document_summary}"
        if log_summary:
            return log_summary
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