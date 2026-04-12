from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload


@dataclass(slots=True)
class KnowledgeRetrieverPhaseExecutor:
    search_documents_tool: Callable[..., Any]
    external_ticket_tool: Callable[..., Any]
    internal_ticket_tool: Callable[..., Any]
    write_shared_memory_tool: Callable[..., Any] | None = None
    write_working_memory_tool: Callable[..., Any] | None = None
    constraint_mode: str = "default"
    highlight_max_chars: int | None = None

    def _uses_summary_constraints(self) -> bool:
        return self.constraint_mode not in {"bypass", "instruction_only"}

    def _invoke_tool(self, tool: Callable[..., Any], *args: object, **kwargs: object) -> str:
        try:
            result = tool(*args, **kwargs)
        except TypeError:
            if kwargs:
                try:
                    signature = inspect.signature(tool)
                    filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
                    result = tool(*args, **filtered_kwargs)
                except (TypeError, ValueError):
                    result = tool(*args)
            else:
                result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(cast(Any, result))
            return str(resolved)
        return str(result)

    @staticmethod
    def _parse_document_result(raw_result: str) -> tuple[str, list[dict[str, object]]]:
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return raw_result, []

        if not isinstance(parsed, dict):
            return raw_result, []

        message = str(parsed.get("message") or "")
        raw_results = parsed.get("results")
        if not isinstance(raw_results, list):
            return message or raw_result, []

        normalized: list[dict[str, object]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "source_name": str(item.get("source_name") or "unknown"),
                    "source_description": str(item.get("source_description") or ""),
                    "source_type": str(item.get("source_type") or "document_source"),
                    "status": str(item.get("status") or "unknown"),
                    "summary": str(item.get("summary") or ""),
                    "path": str(item.get("path") or ""),
                    "route_prefix": str(item.get("route_prefix") or ""),
                    "matched_paths": list(item.get("matched_paths") or []),
                    "evidence": list(item.get("evidence") or []),
                    "feature_bullets": list(item.get("feature_bullets") or []),
                    "raw_backend": item.get("raw_backend") if isinstance(item.get("raw_backend"), dict) else None,
                }
            )
        return message, normalized

    @staticmethod
    def _build_ticket_result(source_name: str, raw_result: str) -> dict[str, object]:
        return {
            "source_name": source_name,
            "source_description": "",
            "source_type": "ticket_source",
            "status": "unavailable" if "not configured" in raw_result or "取得できない" in raw_result else "fetched",
            "summary": raw_result,
            "matched_paths": [],
            "evidence": [],
        }

    @staticmethod
    def _build_skipped_ticket_result(source_name: str, ticket_id: str) -> dict[str, object]:
        return {
            "source_name": source_name,
            "source_description": "",
            "source_type": "ticket_source",
            "status": "skipped",
            "summary": (
                f"{source_name} lookup skipped because the ticket ID was auto-generated for trace correlation: {ticket_id}"
                if ticket_id
                else f"{source_name} lookup skipped because no explicit ticket ID was provided."
            ),
            "matched_paths": [],
            "evidence": [],
        }

    @staticmethod
    def _build_hydrated_ticket_result(source_name: str, summary: str, artifact_paths: list[str]) -> dict[str, object]:
        return {
            "source_name": source_name,
            "source_description": "",
            "source_type": "ticket_source",
            "status": "hydrated",
            "summary": summary,
            "matched_paths": artifact_paths,
            "evidence": [],
        }

    @staticmethod
    def _is_incident_context(state: Mapping[str, object], raw_issue: str) -> bool:
        workflow_kind = str(state.get("workflow_kind") or state.get("intake_category") or "").strip()
        if workflow_kind == "incident_investigation":
            return True
        lowered = raw_issue.lower()
        return any(token in lowered for token in ["error", "exception", "timeout", "fail", "障害", "エラー", ".log", "ログ"])

    @staticmethod
    def _extract_issue_terms(raw_issue: str) -> list[str]:
        candidates: list[str] = []
        normalized = re.sub(r"\s+", " ", raw_issue)
        for match in re.findall(r"\b[\w.$-]+(?:Exception|Error)\b", normalized):
            candidates.append(match.lower())
        for match in re.findall(r"Data source\s+[\w.$-]+\s+not found", normalized, flags=re.IGNORECASE):
            candidates.append(match.lower())
        for match in re.findall(r"\b[a-z0-9_.-]{4,}\b", normalized.lower()):
            if match in {"query", "json", "high", "medium", "low", "none", "true", "false"}:
                continue
            candidates.append(match)

        deduped: list[str] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
            if len(deduped) >= 12:
                break
        return deduped

    @staticmethod
    def _contains_relevant_clue(text: str, issue_terms: list[str]) -> bool:
        lowered = text.lower()
        if any(term and term in lowered for term in issue_terms):
            return True
        return any(marker in lowered for marker in ["exception", "error", "timeout", "stacktrace", "data source"])

    @classmethod
    def _is_relevant_document_result(cls, item: Mapping[str, object], issue_terms: list[str]) -> bool:
        fields: list[str] = [
            str(item.get("source_name") or ""),
            str(item.get("summary") or ""),
            str(item.get("path") or ""),
        ]
        matched_paths = item.get("matched_paths")
        if isinstance(matched_paths, list):
            fields.extend(str(path) for path in matched_paths)
        for key in ("evidence", "feature_bullets"):
            value = item.get(key)
            if isinstance(value, list):
                fields.extend(str(entry) for entry in value)
        return any(cls._contains_relevant_clue(field, issue_terms) for field in fields if field)

    @classmethod
    def _build_document_highlight(
        cls,
        item: Mapping[str, object],
        issue_terms: list[str] | None = None,
        *,
        highlight_max_chars: int | None = None,
    ) -> str:
        issue_terms = issue_terms or []
        feature_bullets = item.get("feature_bullets")
        if isinstance(feature_bullets, list):
            for bullet in feature_bullets:
                text = str(bullet).strip()
                if text and (not issue_terms or cls._contains_relevant_clue(text, issue_terms)):
                    if highlight_max_chars is None or highlight_max_chars <= 0:
                        return text
                    return text[:highlight_max_chars]

        evidence = item.get("evidence")
        if isinstance(evidence, list):
            for bullet in evidence:
                text = str(bullet).strip()
                if text and (not issue_terms or cls._contains_relevant_clue(text, issue_terms)):
                    if highlight_max_chars is None or highlight_max_chars <= 0:
                        return text
                    return text[:highlight_max_chars]

        return ""

    @staticmethod
    def _sanitize_query_for_summary(raw_issue: str) -> str:
        normalized = re.sub(r"\[Additional customer input\].*", "", raw_issue, flags=re.DOTALL).strip()
        return re.sub(r"\s+", " ", normalized)

    def _build_document_summary(
        self,
        raw_issue: str,
        incident_context: bool,
        document_message: str,
        document_results: list[dict[str, object]],
        adopted_sources: list[str],
        apply_constraints: bool,
    ) -> str:
        if not document_results:
            return document_message or "参照可能なドキュメントがないので回答できません。"

        matched_results = [item for item in document_results if str(item.get("status") or "") == "matched"]
        issue_terms = KnowledgeRetrieverPhaseExecutor._extract_issue_terms(raw_issue)
        relevant_results = [
            item for item in matched_results if KnowledgeRetrieverPhaseExecutor._is_relevant_document_result(item, issue_terms)
        ]
        candidate_results = (relevant_results or matched_results or document_results) if apply_constraints else (matched_results or document_results)
        referenced_sources = ", ".join(str(item.get("source_name") or "") for item in candidate_results)
        query_excerpt = (
            KnowledgeRetrieverPhaseExecutor._sanitize_query_for_summary(raw_issue)
            if apply_constraints
            else raw_issue.strip()
        )

        if incident_context and apply_constraints:
            summary = "KnowledgeRetrieverAgent は障害調査の補助として関連資料を確認しました。"
            if query_excerpt:
                summary += f" Query: {query_excerpt}"
            summary += f" 検索対象ソース: {referenced_sources or 'n/a'}。"
            if relevant_results:
                summary += f" 直接関連する資料候補: {', '.join(str(item.get('source_name') or '') for item in relevant_results[:3])}。"
                highlight = self._build_document_highlight(
                    relevant_results[0],
                    issue_terms,
                    highlight_max_chars=self.highlight_max_chars,
                )
                if highlight:
                    summary += f" 要点: {highlight}"
            else:
                summary += " 直接的な障害原因を裏付ける資料は見つかりませんでした。"
            if adopted_sources:
                summary += f" 採用した根拠ソース: {', '.join(adopted_sources)}。"
            return summary.strip()

        summary = "KnowledgeRetrieverAgent は問い合わせ内容をもとに document_sources を検索しました。"
        if query_excerpt:
            summary += f" Query: {query_excerpt}"
        summary += f" 検索対象ソース: {referenced_sources or 'n/a'}。"
        if matched_results:
            matched_path_count = sum(len(cast(list[str], item.get("matched_paths") or [])) for item in matched_results)
            summary += f" 一致したソース数: {len(matched_results)}、参照候補ファイル数: {matched_path_count}。"
            primary_source = str(matched_results[0].get("source_name") or "").strip()
            primary_path = str(matched_results[0].get("path") or "").strip()
            highlight = self._build_document_highlight(
                matched_results[0],
                highlight_max_chars=self.highlight_max_chars,
            )
            if primary_source:
                summary += f" 代表ソース: {primary_source}。"
            if primary_path:
                summary += f" 代表ファイル: {primary_path}。"
            if highlight:
                summary += f" 要点: {highlight}"
        if adopted_sources:
            summary += f" 採用した根拠ソース: {', '.join(adopted_sources)}。"
        return summary.strip()

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+", " ", text.lower()).strip()

    @classmethod
    def _rank_document_result(cls, raw_issue: str, item: Mapping[str, object]) -> tuple[int, int, int, str]:
        normalized_query = cls._normalize_query_text(raw_issue)
        normalized_source_name = cls._normalize_query_text(str(item.get("source_name") or ""))
        explicit_source_match = int(bool(normalized_query and normalized_source_name and normalized_source_name in normalized_query))
        evidence_count = len(item.get("evidence")) if isinstance(item.get("evidence"), list) else 0
        matched_path_count = len(item.get("matched_paths")) if isinstance(item.get("matched_paths"), list) else 0
        return (explicit_source_match, evidence_count, matched_path_count, str(item.get("source_name") or ""))

    @classmethod
    def _prioritize_document_results(cls, raw_issue: str, document_results: list[dict[str, object]]) -> list[dict[str, object]]:
        return sorted(document_results, key=lambda item: cls._rank_document_result(raw_issue, item), reverse=True)

    @staticmethod
    def _build_working_memory_sections(results: list[dict[str, object]]) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        for item in results:
            source_name = str(item.get("source_name") or "unknown").strip() or "unknown"
            sections.append(
                {
                    "title": f"Result: {source_name}",
                    "bullets": [
                        f"Raw result: {json.dumps(item, ensure_ascii=False)}",
                    ],
                }
            )
        return sections

    def execute(self, state: Mapping[str, object]) -> dict[str, object]:
        raw_issue = str(state.get("raw_issue") or "")
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        external_ticket_id = str(state.get("external_ticket_id") or "").strip()
        internal_ticket_id = str(state.get("internal_ticket_id") or "").strip()
        external_ticket_lookup_enabled = bool(state.get("external_ticket_lookup_enabled"))
        internal_ticket_lookup_enabled = bool(state.get("internal_ticket_lookup_enabled"))
        ticket_context = cast(dict[str, str], state.get("intake_ticket_context_summary") or {})
        ticket_artifacts = cast(dict[str, list[str]], state.get("intake_ticket_artifacts") or {})
        apply_runtime_constraints = self._uses_summary_constraints()
        document_message, document_results = self._parse_document_result(
            self._invoke_tool(
                self.search_documents_tool,
                query=raw_issue,
                conversation_messages=cast(list[dict[str, object]], state.get("conversation_messages") or []),
            )
        )
        if apply_runtime_constraints:
            document_results = self._prioritize_document_results(raw_issue, document_results)
        external_hydrated_summary = str(ticket_context.get("external_ticket") or "").strip()
        internal_hydrated_summary = str(ticket_context.get("internal_ticket") or "").strip()
        if external_hydrated_summary or ticket_artifacts.get("external_ticket"):
            external_ticket_result = self._build_hydrated_ticket_result(
                "external_ticket",
                external_hydrated_summary or "IntakeAgent hydrated external ticket context.",
                list(ticket_artifacts.get("external_ticket") or []),
            )
        elif external_ticket_lookup_enabled:
            external_ticket_result = self._build_ticket_result(
                "external_ticket",
                self._invoke_tool(self.external_ticket_tool, ticket_id=external_ticket_id),
            )
        else:
            external_ticket_result = self._build_skipped_ticket_result("external_ticket", external_ticket_id)

        if internal_hydrated_summary or ticket_artifacts.get("internal_ticket"):
            internal_ticket_result = self._build_hydrated_ticket_result(
                "internal_ticket",
                internal_hydrated_summary or "IntakeAgent hydrated internal ticket context.",
                list(ticket_artifacts.get("internal_ticket") or []),
            )
        elif internal_ticket_lookup_enabled:
            internal_ticket_result = self._build_ticket_result(
                "internal_ticket",
                self._invoke_tool(self.internal_ticket_tool, ticket_id=internal_ticket_id),
            )
        else:
            internal_ticket_result = self._build_skipped_ticket_result("internal_ticket", internal_ticket_id)

        results: list[dict[str, object]] = [*document_results, external_ticket_result, internal_ticket_result]
        adopted_sources = [
            str(item.get("source_name") or "")
            for item in document_results
            if str(item.get("status") or "") in {"configured", "matched", "fetched"}
        ]
        summary = self._build_document_summary(
            raw_issue,
            self._is_incident_context(state, raw_issue),
            document_message,
            document_results,
            adopted_sources,
            apply_runtime_constraints,
        )

        if self.write_working_memory_tool is not None and case_id and workspace_path:
            payload: SharedMemoryDocumentPayload = {
                "title": "Knowledge Retrieval Result",
                "heading_level": 2,
                "bullets": [
                    f"Query: {raw_issue or 'n/a'}",
                    f"External ticket ID: {external_ticket_id or 'n/a'}",
                    f"Internal ticket ID: {internal_ticket_id or 'n/a'}",
                    f"External ticket lookup: {'enabled' if external_ticket_lookup_enabled else 'skipped'}",
                    f"Internal ticket lookup: {'enabled' if internal_ticket_lookup_enabled else 'skipped'}",
                    f"Summary: {summary}",
                    f"Adopted sources: {', '.join(adopted_sources) if adopted_sources else 'none'}",
                ],
                "sections": self._build_working_memory_sections(results),
            }
            self._invoke_tool(self.write_working_memory_tool, case_id, workspace_path, payload, "append")

        if self.write_shared_memory_tool is not None and case_id and workspace_path:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Knowledge Retrieval Result",
                "heading_level": 2,
                "bullets": [
                    f"Knowledge retrieval summary: {summary}",
                    f"External ticket lookup: {'enabled' if external_ticket_lookup_enabled else 'skipped'}",
                    f"Internal ticket lookup: {'enabled' if internal_ticket_lookup_enabled else 'skipped'}",
                ],
            }
            if adopted_sources:
                context_payload["bullets"].append(f"Adopted sources: {', '.join(adopted_sources)}")
            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Knowledge Retrieval Result",
                "heading_level": 2,
                "bullets": [
                    f"Knowledge retrieval completed: {'yes' if results else 'no'}",
                    f"External ticket lookup: {'enabled' if external_ticket_lookup_enabled else 'skipped'}",
                    f"Internal ticket lookup: {'enabled' if internal_ticket_lookup_enabled else 'skipped'}",
                ],
            }
            self._invoke_tool(
                self.write_shared_memory_tool,
                case_id,
                workspace_path,
                context_payload,
                progress_payload,
                None,
                "append",
            )

        return {
            "knowledge_retrieval_summary": summary,
            "knowledge_retrieval_results": results,
            "knowledge_retrieval_adopted_sources": adopted_sources,
        }


def build_knowledge_retriever_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        KNOWLEDGE_RETRIEVER_AGENT,
        "Search knowledge sources",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )