from __future__ import annotations

import inspect
import json
from asyncio import run
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.util.asyncio_utils import run_awaitable_sync
from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.log_time_range import apply_derived_log_extract_range

if TYPE_CHECKING:
    from support_ope_agents.models.state import CaseState


@dataclass(slots=True)
class InvestigateAgentTools:
    detect_log_format_tool: Callable[..., Any] | None = None
    infer_log_header_pattern_tool: Callable[..., Any] | None = None
    extract_log_time_range_tool: Callable[..., Any] | None = None
    search_documents_tool: Callable[..., Any] | None = None
    external_ticket_tool: Callable[..., Any] | None = None
    internal_ticket_tool: Callable[..., Any] | None = None
    read_shared_memory_tool: Callable[..., Any] | None = None
    write_shared_memory_tool: Callable[..., Any] | None = None
    write_working_memory_tool: Callable[..., Any] | None = None
    write_draft_tool: Callable[..., Any] | None = None

    @classmethod
    def from_tool_maps(
        cls,
        investigate_tools: Mapping[str, Callable[..., Any]],
        fallback_tools: Mapping[str, Callable[..., Any]] | None = None,
    ) -> "InvestigateAgentTools":
        shared_tools = fallback_tools or {}
        return cls(
            detect_log_format_tool=investigate_tools.get("detect_log_format"),
            infer_log_header_pattern_tool=investigate_tools.get("infer_log_header_pattern"),
            extract_log_time_range_tool=investigate_tools.get("extract_log_time_range"),
            search_documents_tool=investigate_tools.get("search_documents"),
            external_ticket_tool=investigate_tools.get("external_ticket"),
            internal_ticket_tool=investigate_tools.get("internal_ticket"),
            read_shared_memory_tool=investigate_tools.get("read_shared_memory") or shared_tools.get("read_shared_memory"),
            write_shared_memory_tool=investigate_tools.get("write_shared_memory") or shared_tools.get("write_shared_memory"),
            write_working_memory_tool=investigate_tools.get("write_working_memory"),
            write_draft_tool=investigate_tools.get("write_draft"),
        )


@dataclass(slots=True)
class InvestigateAgent(AbstractAgent):
    """
    InvestigateAgentはケースの調査を担当するエージェントで、
    ログ分析、知識取得、調査結果の要約、共有メモリへの書き込みなどの機能を提供します。
    create_node() で Investigate フェーズの実装をLanggraph のDeepAgentノードとして提供します。

    """
    config: AppConfig
    tools: InvestigateAgentTools = field(default_factory=InvestigateAgentTools)

    @classmethod
    def from_tool_maps(
        cls,
        config: AppConfig,
        investigate_tools: Mapping[str, Callable[..., Any]],
        fallback_tools: Mapping[str, Callable[..., Any]] | None = None,
    ) -> "InvestigateAgent":
        return cls(
            config=config,
            tools=InvestigateAgentTools.from_tool_maps(
                investigate_tools,
                fallback_tools=fallback_tools,
            ),
        )

    @staticmethod
    def _default_query() -> str:
        return "調査すべき内容をここに記載してください"

    def _invoke_tool(self, tool: Callable[..., Any] | None, *args: object, **kwargs: object) -> str:
        if tool is None:
            return ""
        result = tool(*args, **kwargs)
        if inspect.isawaitable(result):
            return str(run_awaitable_sync(cast(Any, result)))
        return str(result)

    @staticmethod
    def _find_evidence_log_file(workspace_path: str) -> Path | None:
        workspace_root = Path(workspace_path).expanduser().resolve()
        candidate_dirs = [
            workspace_root / ".artifacts" / "intake" / "external_attachments",
            workspace_root / ".artifacts" / "intake" / "internal_attachments",
            workspace_root / ".evidence",
        ]
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
    def _collect_signal_lines(entries: list[object], *, limit: int = 2) -> list[str]:
        lines: list[str] = []
        for entry in entries[:limit]:
            if isinstance(entry, dict):
                line_number = str(entry.get("line_number") or "").strip()
                line_text = str(entry.get("line") or "").strip()
                if line_text:
                    prefix = f"L{line_number}: " if line_number else ""
                    lines.append(f"{prefix}{line_text}")
            elif str(entry).strip():
                lines.append(str(entry).strip())
        return lines

    def _requested_log_extract_range(self, state: Mapping[str, Any]) -> tuple[str, str] | None:
        normalized_state = dict(state)
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

    def _maybe_extract_log_time_range(self, state: Mapping[str, Any], log_path: Path) -> str:
        requested_range = self._requested_log_extract_range(state)
        workspace_path = str(state.get("workspace_path") or "").strip()
        if requested_range is None or not workspace_path:
            return ""
        if self.tools.infer_log_header_pattern_tool is None or self.tools.extract_log_time_range_tool is None:
            return ""

        range_start, range_end = requested_range
        inferred = json.loads(self._invoke_tool(self.tools.infer_log_header_pattern_tool, str(log_path)))
        if not isinstance(inferred, dict):
            return ""
        header_pattern = str(inferred.get("header_pattern") or "").strip()
        timestamp_start = inferred.get("timestamp_start")
        timestamp_end = inferred.get("timestamp_end")
        if not header_pattern or not isinstance(timestamp_start, int) or not isinstance(timestamp_end, int):
            return ""

        extracted = json.loads(
            self._invoke_tool(
                self.tools.extract_log_time_range_tool,
                str(log_path),
                workspace_path,
                header_pattern,
                timestamp_start,
                timestamp_end,
                range_start,
                range_end,
                str(inferred.get("timestamp_format") or "") or None,
            )
        )
        if not isinstance(extracted, dict):
            return ""
        output_path = str(extracted.get("output_path") or "").strip()
        matched_count = int(extracted.get("matched_record_count") or 0)
        if not output_path:
            return ""
        if matched_count > 0:
            return f"指定時間帯 {range_start} から {range_end} のログ断片を {output_path} に保存しました。"
        return f"指定時間帯 {range_start} から {range_end} に一致するログ断片は見つからず、空の成果物を {output_path} に保存しました。"

    @classmethod
    def _summarize_log_analysis(cls, parsed: dict[str, Any], log_path: Path) -> str:
        search_results = cast(dict[str, list[object]], parsed.get("search_results") or {})
        severity_entries = cast(list[object], search_results.get("severity") or [])
        exception_entries = cast(list[object], search_results.get("java_exception") or [])
        detected_format = str(parsed.get("detected_format") or "unknown")
        severity_names: list[str] = []
        for entry in severity_entries:
            if not isinstance(entry, dict):
                continue
            line = str(entry.get("line") or "")
            for level in ["FATAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"]:
                if level in line and level not in severity_names:
                    severity_names.append(level)
        exception_names: list[str] = []
        for entry in exception_entries:
            if not isinstance(entry, dict):
                continue
            line = str(entry.get("line") or "")
            for token in line.split():
                normalized = token.rstrip(":;,.")
                if normalized.endswith("Exception") or normalized.endswith("Error"):
                    if normalized not in exception_names:
                        exception_names.append(normalized)
        parts = [
            f"{log_path.name} を解析し、形式は {detected_format} と判定しました。",
            f"severity 一致 {len(severity_entries)} 件、例外一致 {len(exception_entries)} 件。",
        ]
        if severity_names:
            parts.append(f"主な severity: {', '.join(severity_names)}。")
        if exception_names:
            parts.append(f"検出した例外候補: {', '.join(exception_names)}。")
        signal_lines = cls._collect_signal_lines(severity_entries or exception_entries, limit=1)
        if signal_lines:
            parts.append(f"代表的な異常行: {signal_lines[0]}。")
        return "".join(parts)

    def _build_ticket_results(self, state: Mapping[str, Any]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        summaries = cast(dict[str, str], state.get("intake_ticket_context_summary") or {})
        artifacts = cast(dict[str, list[str]], state.get("intake_ticket_artifacts") or {})
        for ticket_kind in ("external", "internal"):
            source_name = f"{ticket_kind}_ticket"
            ticket_id = str(state.get(f"{ticket_kind}_ticket_id") or "").strip()
            lookup_enabled = bool(state.get(f"{ticket_kind}_ticket_lookup_enabled"))
            summary = str(summaries.get(source_name) or "").strip()
            if summary:
                results.append(
                    {
                        "source_name": source_name,
                        "source_type": "ticket_source",
                        "status": "hydrated",
                        "summary": summary,
                        "matched_paths": list(artifacts.get(source_name) or []),
                        "evidence": [summary],
                    }
                )
            else:
                status = "skipped" if ticket_id and not lookup_enabled else "unavailable"
                results.append(
                    {
                        "source_name": source_name,
                        "source_type": "ticket_source",
                        "status": status,
                        "summary": "",
                        "matched_paths": [],
                        "evidence": [],
                    }
                )
        return results

    @staticmethod
    def _explicit_source_match(raw_issue: str, item: dict[str, object]) -> int:
        source_name = str(item.get("source_name") or "").strip().lower()
        if not source_name:
            return 0
        normalized_issue = raw_issue.lower()
        return 1 if source_name in normalized_issue else 0

    @classmethod
    def _select_final_source(cls, raw_issue: str, results: list[dict[str, object]]) -> str:
        if not results:
            return ""
        status_priority = {"matched": 3, "hydrated": 2, "fetched": 2, "skipped": 1, "unavailable": 0}
        source_type_priority = {"document_source": 2, "ticket_source": 1}
        ranked = sorted(
            results,
            key=lambda item: (
                cls._explicit_source_match(raw_issue, item),
                status_priority.get(str(item.get("status") or ""), -1),
                source_type_priority.get(str(item.get("source_type") or ""), -1),
                len(cast(list[object], item.get("evidence") or [])),
                len(cast(list[object], item.get("matched_paths") or [])),
            ),
            reverse=True,
        )
        return str(ranked[0].get("source_name") or "").strip()

    @staticmethod
    def _build_knowledge_summary(raw_issue: str, results: list[dict[str, object]], final_source: str) -> str:
        if not results:
            return "参照可能なドキュメントがないので回答できません。"
        matched_results = [item for item in results if str(item.get("status") or "") in {"matched", "hydrated", "fetched"}]
        if not matched_results:
            return f"問い合わせ内容をもとに document_sources を検索しましたが、有効な候補は見つかりませんでした。query: {raw_issue}"
        top = next((item for item in matched_results if str(item.get("source_name") or "") == final_source), matched_results[0])
        evidence = cast(list[str], top.get("evidence") or [])
        summary = str(top.get("summary") or "").strip()
        source_name = str(top.get("source_name") or "").strip()
        parts = [
            f"問い合わせ内容をもとに document_sources を検索しました。query: {raw_issue}",
            f"採用した根拠ソース: {final_source or source_name}",
        ]
        if source_name:
            parts.append(f"代表ソース: {source_name}。")
        if evidence:
            parts.append(f"要点: {evidence[0]}")
        elif summary:
            parts.append(summary)
        return " ".join(part for part in parts if part)

    @staticmethod
    def _build_default_draft(state: Mapping[str, Any]) -> str:
        workflow_kind = str(state.get("workflow_kind") or "")
        raw_issue = str(state.get("raw_issue") or "").strip()
        investigation_summary = str(state.get("investigation_summary") or "").strip()
        if workflow_kind == "incident_investigation":
            return (
                "結論:\n"
                "現時点では障害調査を継続しています。\n\n"
                "原因候補:\n"
                f"{investigation_summary or raw_issue or 'ログと関連資料をもとに切り分け中です。'}\n\n"
                "次アクション:\n"
                "追加ログと発生条件を確認し、再現条件を絞り込みます。"
            )
        return (
            "結論:\n"
            f"{investigation_summary or raw_issue or '関連資料を確認しました。'}\n\n"
            "概要レベルの確認結果:\n"
            "関連資料の要点を整理しました。\n\n"
            "次アクション:\n"
            "必要であれば利用手順や設定差分まで掘り下げます。"
        )

    def create_node(self) -> Any:
        graph = StateGraph(CaseState)
        graph.add_node("investigate_execute", lambda state: cast(CaseState, self.execute(cast(Mapping[str, Any], state))))
        graph.add_edge(START, "investigate_execute")
        graph.add_edge("investigate_execute", END)
        return graph.compile()

    def execute(self, state: Mapping[str, Any]) -> dict[str, Any]:
        update = dict(state)
        query = str(update.get("raw_issue") or "").strip() or self._default_query()
        update["current_agent"] = INVESTIGATE_AGENT
        workspace_path = str(update.get("workspace_path") or "").strip()

        log_summary = ""
        log_file = ""
        log_path = self._find_evidence_log_file(workspace_path) if workspace_path else None
        if log_path is not None and self.tools.detect_log_format_tool is not None:
            try:
                parsed = json.loads(self._invoke_tool(self.tools.detect_log_format_tool, str(log_path), []))
                if isinstance(parsed, dict):
                    log_summary = self._summarize_log_analysis(parsed, log_path)
                    log_file = str(log_path.resolve())
            except Exception:
                log_summary = ""
                log_file = ""
        if log_path is not None:
            try:
                extraction_summary = self._maybe_extract_log_time_range(update, log_path)
            except Exception:
                extraction_summary = ""
            if extraction_summary:
                log_summary = f"{log_summary} {extraction_summary}".strip()

        ticket_results = self._build_ticket_results(update)
        document_results: list[dict[str, object]] = []
        if self.tools.search_documents_tool is not None:
            try:
                payload = json.loads(
                    self._invoke_tool(
                        self.tools.search_documents_tool,
                        query=query,
                        conversation_messages=cast(list[dict[str, object]], update.get("conversation_messages") or []),
                    )
                )
                if isinstance(payload, dict):
                    document_results = [
                        cast(dict[str, object], item)
                        for item in cast(list[object], payload.get("results") or [])
                        if isinstance(item, dict)
                    ]
            except Exception:
                document_results = []

        knowledge_results = ticket_results + document_results
        final_source = self._select_final_source(query, knowledge_results)
        adopted_sources = [final_source] if final_source else []
        knowledge_summary = self._build_knowledge_summary(query, knowledge_results, final_source)

        if log_summary and knowledge_summary:
            update["investigation_summary"] = f"{log_summary} {knowledge_summary}".strip()
        else:
            update["investigation_summary"] = log_summary or knowledge_summary or query
        update["log_analysis_summary"] = log_summary
        update["log_analysis_file"] = log_file
        update["knowledge_retrieval_summary"] = knowledge_summary
        update["knowledge_retrieval_results"] = knowledge_results
        update["knowledge_retrieval_adopted_sources"] = adopted_sources
        update["knowledge_retrieval_final_adopted_source"] = final_source
        if not str(update.get("draft_response") or "").strip():
            draft = self._build_default_draft(update)
            update["draft_response"] = draft
            if self.tools.write_draft_tool is not None and workspace_path and str(update.get("case_id") or "").strip():
                try:
                    run(
                        self.tools.write_draft_tool(
                            str(update.get("case_id") or ""),
                            workspace_path,
                            draft,
                        )
                    )
                except Exception:
                    pass
        return update

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