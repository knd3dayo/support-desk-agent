from __future__ import annotations

import inspect
import json
from asyncio import run
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, cast

from langgraph.graph import END, START, StateGraph

from support_desk_agent.agents.abstract_agent import AbstractAgent
from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_desk_agent.models.state import as_state_dict
from support_desk_agent.util.asyncio_utils import run_awaitable_sync
from support_desk_agent.config.models import AppConfig
from support_desk_agent.util.formatting import format_result
from support_desk_agent.util.log_time_range import apply_derived_log_extract_range
from support_desk_agent.workspace import find_evidence_log_file

if TYPE_CHECKING:
    from support_desk_agent.models.state import CaseState


@dataclass(slots=True)
class InvestigateAgentTools:
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
        normalized_state = as_state_dict(state)
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
        if self.tools.extract_log_time_range_tool is None:
            return ""

        range_start, range_end = requested_range
        extracted = json.loads(
            self._invoke_tool(
                self.tools.extract_log_time_range_tool,
                str(log_path),
                workspace_path,
                range_start,
                range_end,
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
        from support_desk_agent.models.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("investigate_execute", lambda state: cast(CaseState, self.execute(cast(Mapping[str, Any], state))))
        graph.add_edge(START, "investigate_execute")
        graph.add_edge("investigate_execute", END)
        return graph.compile()

    def execute(self, state: Mapping[str, Any]) -> dict[str, Any]:
        update = as_state_dict(state)
        query = str(update.get("raw_issue") or "").strip() or self._default_query()
        update["current_agent"] = INVESTIGATE_AGENT
        workspace_path = str(update.get("workspace_path") or "").strip()
        attachment_ignore_patterns = self.config.data_paths.attachment_ignore_patterns

        log_summary = ""
        log_file = ""
        log_path = (
            find_evidence_log_file(
                workspace_path,
                include_attachment_dirs=True,
                ignore_patterns=attachment_ignore_patterns,
            )
            if workspace_path
            else None
        )
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