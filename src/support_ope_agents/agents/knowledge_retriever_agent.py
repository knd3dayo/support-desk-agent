from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import KNOWLEDGE_RETRIEVER_AGENT, SUPERVISOR_AGENT


@dataclass(slots=True)
class KnowledgeRetrieverPhaseExecutor:
    search_documents_tool: Callable[..., Any]
    external_ticket_tool: Callable[..., Any]
    internal_ticket_tool: Callable[..., Any]

    def _invoke_tool(self, tool: Callable[..., Any], *args: object, **kwargs: object) -> str:
        result = tool(*args, **kwargs)
        if inspect.isawaitable(result):
            try:
                resolved = asyncio.run(cast(Coroutine[Any, Any, Any], result))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    resolved = loop.run_until_complete(result)
                finally:
                    loop.close()
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

    def execute(self, state: Mapping[str, object]) -> dict[str, object]:
        raw_issue = str(state.get("raw_issue") or "")
        document_message, document_results = self._parse_document_result(
            self._invoke_tool(self.search_documents_tool, query=raw_issue)
        )
        external_ticket_result = self._build_ticket_result(
            "external_ticket",
            self._invoke_tool(self.external_ticket_tool),
        )
        internal_ticket_result = self._build_ticket_result(
            "internal_ticket",
            self._invoke_tool(self.internal_ticket_tool),
        )

        results: list[dict[str, object]] = [*document_results, external_ticket_result, internal_ticket_result]
        adopted_sources = [
            str(item.get("source_name") or "")
            for item in document_results
            if str(item.get("status") or "") in {"configured", "matched", "fetched"}
        ]
        if not document_results:
            summary = document_message or "参照可能なドキュメントがないので回答できません。"
        else:
            referenced_sources = ", ".join(str(item["source_name"]) for item in document_results)
            summary = f"KnowledgeRetrieverAgent は次の document_sources を調査対象として扱います: {referenced_sources}"

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