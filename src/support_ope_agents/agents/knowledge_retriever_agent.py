from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import (
    AppConfig,
    DEFAULT_DOCUMENT_IGNORE_PATTERNS,
    KnowledgeDocumentSource,
    KnowledgeSearchStrategy,
)
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.tools.default_search_documents import _invoke_deepagents_search
from support_ope_agents.tools.document_source_backend import (
    build_document_source_backend,
    candidate_virtual_paths_for_source,
    extract_feature_bullets_with_options,
    extract_relevant_snippet_with_limit,
    grep_backend_matches,
    read_backend_content_with_limit,
)
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload


@dataclass(slots=True)
class KnowledgeRetrieverPhaseExecutor:
    external_ticket_tool: Callable[..., Any]
    internal_ticket_tool: Callable[..., Any]
    config: AppConfig | None = None
    document_sources: list[KnowledgeDocumentSource] = field(default_factory=list)
    search_documents_tool: Callable[..., Any] | None = None
    write_shared_memory_tool: Callable[..., Any] | None = None
    write_working_memory_tool: Callable[..., Any] | None = None
    constraint_mode: str = "default"
    highlight_max_chars: int | None = None
    search_strategy: KnowledgeSearchStrategy = "hybrid"
    result_mode: Literal["relaxed", "raw_backend"] = "relaxed"
    backend_read_char_limit: int | None = 8000
    max_evidence_count: int = 3
    candidate_path_limit: int = 5
    persist_raw_search_snapshot: bool = False

    def _uses_summary_constraints(self) -> bool:
        # Runtime constraint: result prioritization and summary shaping are skipped in bypass and instruction_only.
        return RuntimeHarnessManager.summary_constraints_enabled_for_mode(self.constraint_mode)

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

    def _resolve_document_sources(self) -> list[KnowledgeDocumentSource]:
        if self.document_sources:
            return self.document_sources
        if self.config is not None:
            return list(self.config.agents.InvestigateAgent.document_sources)
        return []

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _dict_list(value: object) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _merge_unique_strings(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for item in group:
                normalized = str(item).strip()
                if normalized and normalized not in merged:
                    merged.append(normalized)
        return merged

    def _collect_backend_context(self, backend: Any, source: KnowledgeDocumentSource, query: str) -> dict[str, object]:
        route_prefix = f"/knowledge/{source.name}/"
        candidate_paths = candidate_virtual_paths_for_source(
            backend=backend,
            source=source,
            route_base="knowledge",
            ignore_patterns=DEFAULT_DOCUMENT_IGNORE_PATTERNS,
            limit=self.candidate_path_limit,
        )
        primary_path = candidate_paths[0] if candidate_paths else ""
        primary_content = (
            read_backend_content_with_limit(backend, primary_path, self.backend_read_char_limit) if primary_path else ""
        )
        grep_matches = grep_backend_matches(
            backend,
            query,
            route_prefix,
            max_items=self.max_evidence_count,
            ignore_patterns=DEFAULT_DOCUMENT_IGNORE_PATTERNS,
        )
        evidence = [str(match.get("text") or "").strip() for match in grep_matches if str(match.get("text") or "").strip()]
        feature_bullets = extract_feature_bullets_with_options(
            primary_content,
            query,
            require_query_match=False,
            heading_keywords=None,
            max_items=5,
        )
        summary = extract_relevant_snippet_with_limit(primary_content, query, 600) if primary_content else ""
        return {
            "route_prefix": route_prefix,
            "candidate_paths": candidate_paths,
            "primary_path": primary_path,
            "primary_content": primary_content,
            "grep_matches": grep_matches,
            "evidence": evidence,
            "feature_bullets": feature_bullets,
            "summary": summary,
        }

    def _search_with_deepagents(
        self,
        *,
        backend: Any,
        sources: list[KnowledgeDocumentSource],
        query: str,
        conversation_messages: list[dict[str, object]] | None,
    ) -> dict[str, dict[str, Any]]:
        if self.config is None:
            raise RuntimeError("KnowledgeRetrieverAgent requires AppConfig for deepagents and hybrid strategies.")
        normalized = _invoke_deepagents_search(
            config=self.config,
            backend=backend,
            sources=sources,
            query=query,
            extraction_mode=self.result_mode,
            conversation_messages=conversation_messages,
        )
        if normalized is None:
            if self.search_strategy == "deepagents":
                raise RuntimeError("DeepAgents search did not return a structured response.")
            return {}
        return normalized

    def _compose_document_result(
        self,
        *,
        source: KnowledgeDocumentSource,
        normalized: Mapping[str, object] | None,
        backend_context: Mapping[str, object],
    ) -> dict[str, object]:
        route_prefix = str(backend_context.get("route_prefix") or f"/knowledge/{source.name}/")
        candidate_paths = self._string_list(backend_context.get("candidate_paths"))
        normalized_paths = self._string_list((normalized or {}).get("matched_paths"))
        backend_evidence = self._string_list(backend_context.get("evidence"))
        backend_feature_bullets = self._string_list(backend_context.get("feature_bullets"))
        normalized_evidence = self._string_list((normalized or {}).get("evidence"))
        normalized_feature_bullets = self._string_list((normalized or {}).get("feature_bullets"))
        backend_summary = str(backend_context.get("summary") or "").strip()
        normalized_summary = str((normalized or {}).get("summary") or "").strip()
        deepagents_status = str((normalized or {}).get("status") or "unavailable").strip()

        if self.search_strategy == "backend_only":
            status = "matched" if candidate_paths else "unavailable"
            matched_paths = candidate_paths
            evidence = backend_evidence
            feature_bullets = backend_feature_bullets
            summary = backend_summary or ("参照対象パスに関連箇所が見つかりませんでした。" if candidate_paths else "参照対象パスに概要取得可能な Markdown 文書が見つかりません。")
        elif self.search_strategy == "deepagents":
            status = deepagents_status
            matched_paths = normalized_paths or candidate_paths
            evidence = normalized_evidence
            feature_bullets = normalized_feature_bullets
            summary = normalized_summary or backend_summary or "DeepAgents search did not return a result for this source."
        else:
            status = "matched" if deepagents_status == "matched" or candidate_paths else "unavailable"
            matched_paths = self._merge_unique_strings(normalized_paths, candidate_paths)
            evidence = self._merge_unique_strings(normalized_evidence, backend_evidence)
            feature_bullets = self._merge_unique_strings(normalized_feature_bullets, backend_feature_bullets)
            summary = normalized_summary or backend_summary or "document_sources から関連箇所を抽出しました。"

        result_payload: dict[str, object] = {
            "source_name": source.name,
            "source_description": source.description,
            "source_type": "document_source",
            "status": status,
            "summary": summary,
            "path": str(source.path),
            "route_prefix": route_prefix,
            "matched_paths": matched_paths,
            "evidence": evidence[: self.max_evidence_count],
            "feature_bullets": feature_bullets[:5],
        }

        if self.result_mode == "raw_backend":
            primary_content = str(backend_context.get("primary_content") or "")
            raw_backend: dict[str, object] = {
                "mode": self.result_mode,
                "file_data": {"content": primary_content} if primary_content else None,
                "candidate_paths": candidate_paths,
                "grep_matches": self._dict_list(backend_context.get("grep_matches")),
            }
            llm_excerpt = str((normalized or {}).get("raw_content") or "").strip()
            if llm_excerpt:
                raw_backend["llm_excerpt"] = llm_excerpt
                if raw_backend["file_data"] is None:
                    raw_backend["file_data"] = {"content": llm_excerpt}
            result_payload["raw_backend"] = raw_backend

        return result_payload

    def _search_documents(
        self,
        *,
        query: str,
        conversation_messages: list[dict[str, object]] | None,
    ) -> tuple[str, list[dict[str, object]], dict[str, object] | None]:
        if self.search_documents_tool is not None:
            message, results = self._parse_document_result(
                self._invoke_tool(
                    self.search_documents_tool,
                    query=query,
                    conversation_messages=conversation_messages,
                )
            )
            snapshot = {
                "search_strategy": "tool_override",
                "result_mode": self.result_mode,
                "query": query,
                "results": results,
            }
            return message, results, snapshot

        sources = self._resolve_document_sources()
        if not sources:
            return "参照可能なドキュメントがないので回答できません。", [], None

        backend = build_document_source_backend(document_sources=cast(Any, sources), route_base="knowledge")
        if backend is None:
            raise RuntimeError("Knowledge document backend could not be initialized. Check KnowledgeRetrieverAgent.document_sources.")

        normalized_by_source: dict[str, dict[str, Any]] = {}
        if self.search_strategy in {"deepagents", "hybrid"}:
            normalized_by_source = self._search_with_deepagents(
                backend=backend,
                sources=sources,
                query=query,
                conversation_messages=conversation_messages,
            )

        results: list[dict[str, object]] = []
        snapshot_sources: list[dict[str, object]] = []
        for source in sources:
            backend_context = self._collect_backend_context(backend, source, query)
            normalized = normalized_by_source.get(source.name)
            result_payload = self._compose_document_result(
                source=source,
                normalized=normalized,
                backend_context=backend_context,
            )
            results.append(result_payload)
            snapshot_sources.append(
                {
                    "source_name": source.name,
                    "strategy": self.search_strategy,
                    "normalized": normalized,
                    "backend_context": backend_context,
                    "result": result_payload,
                }
            )

        matched_any = any(str(item.get("status") or "") == "matched" for item in results)
        message = "document_sources から関連箇所を抽出しました。" if matched_any else "参照可能なドキュメントがないので回答できません。"
        snapshot = {
            "search_strategy": self.search_strategy,
            "result_mode": self.result_mode,
            "query": query,
            "sources": snapshot_sources,
        }
        return message, results, snapshot

    def _write_search_snapshot(self, case_id: str, workspace_path: str, snapshot: Mapping[str, object] | None) -> None:
        if not self.persist_raw_search_snapshot or snapshot is None or self.config is None:
            return
        memory_store = CaseMemoryStore(self.config)
        working_file = memory_store.ensure_agent_working_memory(case_id, KNOWLEDGE_RETRIEVER_AGENT, workspace_path=workspace_path)
        snapshot_path = working_file.parent / "search-results.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
        evidence = item.get("evidence")
        matched_paths = item.get("matched_paths")
        evidence_count = len(evidence) if isinstance(evidence, list) else 0
        matched_path_count = len(matched_paths) if isinstance(matched_paths, list) else 0
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
        document_message, document_results, search_snapshot = self._search_documents(
            query=raw_issue,
            conversation_messages=cast(list[dict[str, object]], state.get("conversation_messages") or []),
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

        if case_id and workspace_path:
            self._write_search_snapshot(case_id, workspace_path, search_snapshot)

        if self.write_working_memory_tool is not None and case_id and workspace_path:
            payload: SharedMemoryDocumentPayload = {
                "title": "Knowledge Retrieval Result",
                "heading_level": 2,
                "bullets": [
                    f"Query: {raw_issue or 'n/a'}",
                    f"Search strategy: {self.search_strategy}",
                    f"Result mode: {self.result_mode}",
                    f"External ticket ID: {external_ticket_id or 'n/a'}",
                    f"Internal ticket ID: {internal_ticket_id or 'n/a'}",
                    f"External ticket lookup: {'enabled' if external_ticket_lookup_enabled else 'skipped'}",
                    f"Internal ticket lookup: {'enabled' if internal_ticket_lookup_enabled else 'skipped'}",
                    f"Summary: {summary}",
                    f"Adopted sources: {', '.join(adopted_sources) if adopted_sources else 'none'}",
                ],
                "sections": cast(Any, self._build_working_memory_sections(results)),
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


    @staticmethod
    def build_knowledge_retriever_agent_definition() -> AgentDefinition:
        return AgentDefinition(
            KNOWLEDGE_RETRIEVER_AGENT,
            "Search knowledge sources",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )
