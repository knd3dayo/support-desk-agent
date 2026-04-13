from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from support_ope_agents.config.models import AppConfig, KnowledgeDocumentSource
from support_ope_agents.runtime.conversation_messages import deserialize_langchain_messages

from .document_source_backend import build_document_source_backend, read_backend_file_data

try:
    from deepagents import create_deep_agent
except Exception:  # pragma: no cover
    create_deep_agent = None


class _DeepAgentSourceResult(BaseModel):
    source_name: str = ""
    status: Literal["matched", "unavailable"] = "matched"
    summary: str = ""
    matched_paths: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    feature_bullets: list[str] = Field(default_factory=list)
    raw_content: str = ""


class _DeepAgentSearchResponse(BaseModel):
    results: list[_DeepAgentSourceResult] = Field(default_factory=list)


def _get_chat_model(config: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        temperature=0,
    )


def _build_search_prompt(
    *,
    query: str,
    sources: list[KnowledgeDocumentSource],
    extraction_mode: Literal["relaxed", "raw_backend"],
) -> str:
    mode_instruction = (
        "関連語や言い換えも含めて広めに探索し、もっとも関連の強い根拠を抽出してください。"
        if extraction_mode == "relaxed"
        else "診断用途なので、もっとも関連の強い文書の生テキストも保持してください。"
    )
    source_lines = "\n".join(
        f"- {source.name}: {source.description} (route: /knowledge/{source.name}/)"
        for source in sources
    )
    return (
        "あなたはドキュメント検索担当です。\n"
        "Filesystem tools だけを使い、指定された route 配下の文書だけを根拠にしてください。\n"
        "ファイル編集やコマンド実行は行わないでください。\n"
        f"検索対象 source 一覧:\n{source_lines}\n"
        f"問い合わせ: {query}\n"
        f"追加指示: {mode_instruction}\n"
        "返却ルール:\n"
        "- results は source ごとの配列にする\n"
        "- source_name は必ず source 一覧の name を使う\n"
        "- status は matched か unavailable\n"
        "- summary には最重要箇所の抜粋を入れる\n"
        "- matched_paths には関連度順の backend path を入れる\n"
        "- evidence には根拠となる短い原文断片を入れる\n"
        "- feature_bullets は機能一覧問い合わせのときだけ入れる\n"
        "- raw_content は raw_backend のときだけ最重要ファイル本文を入れ、それ以外は空文字にする\n"
        "- 事実を捏造しないこと\n"
    )


def _invoke_deepagents_search(
    *,
    config: AppConfig,
    backend: Any,
    sources: list[KnowledgeDocumentSource],
    query: str,
    extraction_mode: Literal["relaxed", "raw_backend"],
    conversation_messages: list[dict[str, object]] | None = None,
) -> dict[str, dict[str, Any]] | None:
    if create_deep_agent is None:
        return None

    agent = create_deep_agent(
        model=_get_chat_model(config),
        backend=backend,
        system_prompt=(
            "Search the mounted documentation and return only structured data. "
            "Use filesystem tools to inspect documents under the allowed routes."
        ),
        response_format=_DeepAgentSearchResponse,
        tools=[],
        name="knowledge-document-search",
    )
    result = agent.invoke(
        {
            "messages": [
                *deserialize_langchain_messages(conversation_messages),
                HumanMessage(
                    content=_build_search_prompt(
                        query=query,
                        sources=sources,
                        extraction_mode=extraction_mode,
                    )
                )
            ]
        }
    )
    if not isinstance(result, dict):
        return None
    structured = result.get("structured_response")
    if isinstance(structured, _DeepAgentSearchResponse):
        return {
            item.source_name: item.model_dump()
            for item in structured.results
            if item.source_name.strip()
        }
    if isinstance(structured, dict):
        parsed = _DeepAgentSearchResponse.model_validate(structured)
        return {
            item.source_name: item.model_dump()
            for item in parsed.results
            if item.source_name.strip()
        }
    return None


def build_default_search_documents_tool(config: AppConfig):
    settings = config.agents.KnowledgeRetrieverAgent

    def _search_documents(*, query: str = "", conversation_messages: list[dict[str, object]] | None = None) -> str:
        if not settings.document_sources:
            payload = {
                "status": "unavailable",
                "message": "参照可能なドキュメントがないので回答できません。agents.KnowledgeRetrieverAgent.document_sources を設定してください。",
                "query": query,
                "results": [],
            }
            return json.dumps(payload, ensure_ascii=False)

        backend = build_document_source_backend(document_sources=settings.document_sources, route_base="knowledge")
        if backend is None:
            raise RuntimeError(
                "Knowledge document backend could not be initialized. Check agents.KnowledgeRetrieverAgent.document_sources."
            )
        if create_deep_agent is None:
            raise RuntimeError("DeepAgents search is unavailable because deepagents could not be imported.")

        normalized_by_source = _invoke_deepagents_search(
            config=config,
            backend=backend,
            sources=settings.document_sources,
            query=query,
            extraction_mode=settings.extraction_mode,
            conversation_messages=conversation_messages,
        )
        if normalized_by_source is None:
            raise RuntimeError("DeepAgents search did not return a structured response.")

        results: list[dict[str, object]] = []
        for source in settings.document_sources:
            route_prefix = f"/knowledge/{source.name}/"
            normalized = normalized_by_source.get(source.name) or {
                "source_name": source.name,
                "status": "unavailable",
                "summary": "DeepAgents search did not return a result for this source.",
                "matched_paths": [],
                "evidence": [],
                "feature_bullets": [],
                "raw_content": "",
            }
            result_payload: dict[str, object] = {
                "source_name": source.name,
                "source_description": source.description,
                "source_type": "document_source",
                "status": str(normalized.get("status") or "unknown"),
                "summary": str(normalized.get("summary") or ""),
                "path": str(source.path),
                "route_prefix": route_prefix,
                "matched_paths": list(normalized.get("matched_paths") or []),
                "evidence": [str(item).strip() for item in list(normalized.get("evidence") or []) if str(item).strip()],
                "feature_bullets": [str(item).strip() for item in list(normalized.get("feature_bullets") or []) if str(item).strip()],
            }
            if settings.extraction_mode == "raw_backend":
                raw_content = str(normalized.get("raw_content") or "")
                primary_path = str((result_payload["matched_paths"] or [""])[0])
                result_payload["raw_backend"] = {
                    "mode": settings.extraction_mode,
                    "file_data": {"content": raw_content}
                    if raw_content
                    else (read_backend_file_data(backend, primary_path) if primary_path else None),
                }
            results.append(result_payload)

        payload = {
            "status": "matched",
            "message": "document_sources から関連箇所を抽出しました。",
            "query": query,
            "results": results,
        }
        return json.dumps(payload, ensure_ascii=False)

    return _search_documents
