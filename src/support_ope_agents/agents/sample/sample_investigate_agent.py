from __future__ import annotations

import argparse
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.asyncio_utils import run_awaitable_sync
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.tools.builtin_tools import build_builtin_tools
from support_ope_agents.tools.builtin_tools import _detect_log_format_from_lines
from support_ope_agents.tools.builtin_tools import _extract_text_from_path
from support_ope_agents.tools.builtin_tools import _search_log_with_patterns
from support_ope_agents.tools.default_write_working_memory import build_default_write_working_memory_tool
from support_ope_agents.util.document import build_filtered_document_source_backend
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.util.log_time_range import apply_derived_log_extract_range

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
        builtin_tools = build_builtin_tools(config)
        self._infer_log_header_pattern_tool = builtin_tools["infer_log_header_pattern"].handler
        self._extract_log_time_range_tool = builtin_tools["extract_log_time_range"].handler
        self._write_working_memory_tool = build_default_write_working_memory_tool(config, INVESTIGATE_AGENT)

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    def _build_system_prompt(self, query: str, instruction_text: str = "") -> str:
        prompt = (
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
        instruction = instruction_text.strip()
        if instruction:
            prompt = f"{prompt}\n\n追加 instruction:\n{instruction}"
        return prompt

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

    @staticmethod
    def _invoke_tool(tool: Any, *args: object, **kwargs: object) -> str:
        result = tool(*args, **kwargs)
        if inspect.isawaitable(result):
            return str(run_awaitable_sync(result))
        return str(result)

    def _requested_log_extract_range(self, state: dict[str, Any] | None) -> tuple[str, str] | None:
        normalized_state = dict(state or {})
        apply_derived_log_extract_range(
            normalized_state,
            str(normalized_state.get("intake_incident_timeframe") or ""),
            config=self.config,
        )
        start = str(normalized_state.get("log_extract_range_start") or "").strip()
        end = str(normalized_state.get("log_extract_range_end") or "").strip()
        if start and end:
            return start, end
        return None

    def _maybe_extract_log_time_range(self, state: dict[str, Any] | None, workspace_path: str | None, log_path: Path) -> str:
        requested_range = self._requested_log_extract_range(state)
        if requested_range is None or not workspace_path:
            return ""
        range_start, range_end = requested_range
        inferred_payload = json.loads(
            self._invoke_tool(self._infer_log_header_pattern_tool, file_path=str(log_path), sample_line_limit=100)
        )
        if not isinstance(inferred_payload, dict):
            return ""
        header_pattern = str(inferred_payload.get("header_pattern") or "").strip()
        timestamp_start = inferred_payload.get("timestamp_start")
        timestamp_end = inferred_payload.get("timestamp_end")
        if not header_pattern or not isinstance(timestamp_start, int) or not isinstance(timestamp_end, int):
            return ""
        extracted_payload = json.loads(
            self._invoke_tool(
                self._extract_log_time_range_tool,
                file_path=str(log_path),
                workspace_path=workspace_path,
                header_pattern=header_pattern,
                timestamp_start=timestamp_start,
                timestamp_end=timestamp_end,
                range_start=range_start,
                range_end=range_end,
                time_format=str(inferred_payload.get("timestamp_format") or "") or None,
            )
        )
        if not isinstance(extracted_payload, dict):
            return ""
        output_path = str(extracted_payload.get("output_path") or "").strip()
        matched_count = int(extracted_payload.get("matched_record_count") or 0)
        if not output_path:
            return ""
        if matched_count > 0:
            return f"指定時間帯 {range_start} から {range_end} のログ断片を {output_path} に保存しました。"
        return f"指定時間帯 {range_start} から {range_end} に一致するログ断片は見つからず、空の成果物を {output_path} に保存しました。"

    def _write_working_memory(
        self,
        *,
        state: dict[str, Any] | None,
        workspace_path: str | None,
        query: str,
        log_path: Path | None,
        log_summary: str,
        document_summary: str,
        extraction_summary: str,
        instruction_text: str,
    ) -> None:
        normalized_state = dict(state or {})
        case_id = str(normalized_state.get("case_id") or "").strip()
        normalized_workspace_path = str(workspace_path or normalized_state.get("workspace_path") or "").strip()
        if not case_id or not normalized_workspace_path:
            return

        bullets = [
            f"Query: {query}",
            f"Evidence log: {log_path.name if log_path is not None else 'n/a'}",
            f"Incident timeframe: {str(normalized_state.get('intake_incident_timeframe') or 'n/a').strip() or 'n/a'}",
            f"Requested extract range: {str(normalized_state.get('log_extract_range_start') or 'n/a').strip() or 'n/a'} -> {str(normalized_state.get('log_extract_range_end') or 'n/a').strip() or 'n/a'}",
        ]
        sections: list[dict[str, object]] = [
            {"title": "Log Findings", "summary": log_summary or "n/a"},
            {"title": "Document Findings", "summary": document_summary or "n/a"},
        ]
        if extraction_summary:
            sections.append({"title": "Log Extraction", "summary": extraction_summary})
        if instruction_text.strip():
            bullets.append("Instruction provided: yes")

        try:
            self._invoke_tool(
                self._write_working_memory_tool,
                case_id,
                normalized_workspace_path,
                {"title": "Investigate Result", "heading_level": 2, "bullets": bullets, "sections": sections},
                "append",
            )
        except Exception:
            return

    @staticmethod
    def _augment_query_with_evidence(query: str, log_path: Path | None, log_summary: str) -> str:
        if log_path is None or not log_summary.strip():
            return query
        evidence_section = (
            "workspace 上の evidence ログは既に確認済みです。"
            f"\nEvidence file: {log_path.name}"
            f"\nEvidence path: {log_path}"
            f"\nEvidence summary: {log_summary.strip()}"
        )
        parts = [part for part in (query.strip(), evidence_section) if part]
        return "\n\n".join(parts)

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
            "not found",
            "missing",
            "does not exist",
        )
        return log_path.name.lower() in normalized and any(marker in normalized for marker in missing_markers)

    def create_sub_agent(self, *, query: str | None = None, instruction_text: str = "") -> Any:
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
            system_prompt=self._build_system_prompt(effective_query, instruction_text=instruction_text),
            tools=[],
            name="investigate-agent",
        )
        return agent

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
        log_summary = self._summarize_workspace_log(workspace_path)
        log_path = self._find_evidence_log_file(workspace_path) if workspace_path else None
        investigation_query = self._augment_query_with_evidence(effective_query, log_path, log_summary)
        extraction_summary = ""
        if log_path is not None:
            try:
                extraction_summary = self._maybe_extract_log_time_range(state, workspace_path, log_path)
            except Exception as exc:
                extraction_summary = f"ログ抽出は失敗しました: {exc}"
            if extraction_summary:
                log_summary = f"{log_summary} {extraction_summary}".strip()

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
            if log_summary:
                self._write_working_memory(
                    state=state,
                    workspace_path=workspace_path,
                    query=effective_query,
                    log_path=log_path,
                    log_summary=log_summary,
                    document_summary="deep agent invocation failed; returned log-only summary",
                    extraction_summary=extraction_summary,
                    instruction_text=instruction_text or "",
                )
                return log_summary
            raise

        document_summary = extract_result_output_text(result) or format_result(result)
        if self._is_contradictory_document_summary(document_summary, log_path):
            document_summary = ""
        self._write_working_memory(
            state=state,
            workspace_path=workspace_path,
            query=effective_query,
            log_path=log_path,
            log_summary=log_summary,
            document_summary=document_summary,
            extraction_summary=extraction_summary,
            instruction_text=instruction_text or "",
        )
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