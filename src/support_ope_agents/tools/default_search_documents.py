from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig

from .document_source_backend import (
    build_document_source_backend,
    candidate_virtual_paths_for_source,
    extract_feature_bullets_with_options,
    extract_relevant_snippet_with_limit,
    glob_backend_matches,
    grep_backend_evidence_with_limit,
    grep_backend_matches,
    load_ignore_patterns,
    read_backend_content_with_limit,
    read_backend_file_data,
)


def _get_chat_model(config: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        temperature=0,
    )


def _stringify_response_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    return str(content).strip()


def _normalize_keywords(values: list[str], limit: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if len(value) < 2:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
        if len(normalized) >= limit:
            break
    return normalized


def _expand_search_keywords(config: AppConfig, query: str, limit: int) -> list[str]:
    if not query.strip() or limit <= 0:
        return []
    model = _get_chat_model(config)

    prompt = {
        "task": "Expand the user query into related search keywords for documentation retrieval.",
        "query": query,
        "max_keywords": limit,
        "output_format": {"keywords": ["string"]},
    }
    response = model.invoke(
        [HumanMessage(content="Return JSON only. Generate concise search keywords.\n" + json.dumps(prompt, ensure_ascii=False))]
    )
    content = _stringify_response_content(response.content)
    parsed = json.loads(content)
    if isinstance(parsed, dict):
        return _normalize_keywords(list(parsed.get("keywords") or []), limit)
    raise ValueError("search keyword expansion returned an invalid payload")


def build_default_search_documents_tool(config: AppConfig):
    settings = config.agents.KnowledgeRetrieverAgent
    ignore_patterns = load_ignore_patterns(settings.ignore_patterns, settings.ignore_patterns_file)

    def _effective_limit(current: int | None, relaxed_floor: int | None) -> int | None:
        if settings.extraction_mode == "raw_backend":
            return None if relaxed_floor is None else current
        if settings.extraction_mode == "relaxed" and current is not None and relaxed_floor is not None:
            return max(current, relaxed_floor)
        return current

    def _search_documents(*, query: str = "") -> str:
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
            payload = {
                "status": "unavailable",
                "message": "参照可能なドキュメントがないので回答できません。agents.KnowledgeRetrieverAgent.document_sources を設定してください。 DeepAgents backend を初期化できませんでした。",
                "query": query,
                "results": [],
            }
            return json.dumps(payload, ensure_ascii=False)

        expanded_keywords = (
            _expand_search_keywords(config, query, settings.search_keyword_expansion_count)
            if settings.search_keyword_expansion_enabled
            else []
        )
        search_keywords = _normalize_keywords(
            [*settings.search_keywords, *expanded_keywords],
            max(1, len(settings.search_keywords) + settings.search_keyword_expansion_count),
        )

        results: list[dict[str, object]] = []
        for source in settings.document_sources:
            route_prefix = f"/knowledge/{source.name}/"
            candidate_paths = candidate_virtual_paths_for_source(
                backend=backend,
                source=source,
                route_base="knowledge",
                ignore_patterns=ignore_patterns,
                limit=_effective_limit(settings.candidate_path_limit, 20),
            )
            if not candidate_paths:
                results.append(
                    {
                        "source_name": source.name,
                        "source_description": source.description,
                        "source_type": "document_source",
                        "status": "unavailable",
                        "summary": "参照対象パスに概要取得可能な Markdown 文書が見つかりません。",
                        "path": str(source.path),
                        "route_prefix": route_prefix,
                        "matched_paths": [],
                        "evidence": [],
                        "feature_bullets": [],
                    }
                )
                continue

            primary_content = read_backend_content_with_limit(
                backend,
                candidate_paths[0],
                _effective_limit(settings.backend_read_char_limit, 32000),
            )
            raw_matches = grep_backend_matches(
                backend,
                query,
                route_prefix,
                extra_keywords=search_keywords,
                max_items=settings.raw_backend_max_matches if settings.extraction_mode == "raw_backend" else _effective_limit(settings.max_evidence_count, 20),
            )
            result_payload: dict[str, object] = {
                "source_name": source.name,
                "source_description": source.description,
                "source_type": "document_source",
                "status": "matched",
                "summary": (
                    primary_content.strip()
                    if settings.extraction_mode == "raw_backend"
                    else extract_relevant_snippet_with_limit(
                        primary_content,
                        query,
                        _effective_limit(settings.summary_max_chars, 2000),
                    )
                    or f"{source.name} から関連箇所を抽出しました。"
                ),
                "path": str(source.path),
                "route_prefix": route_prefix,
                "matched_paths": candidate_paths[:3] if settings.extraction_mode != "raw_backend" else candidate_paths,
                "evidence": [str(match.get("text") or "").strip() for match in raw_matches],
                "feature_bullets": []
                if settings.extraction_mode == "raw_backend"
                else extract_feature_bullets_with_options(
                    primary_content,
                    query,
                    require_query_match=settings.extraction_mode == "limited",
                    heading_keywords=settings.feature_heading_keywords,
                    max_items=_effective_limit(settings.feature_bullet_max_items, 20),
                ),
            }
            if settings.extraction_mode == "raw_backend":
                result_payload["raw_backend"] = {
                    "mode": settings.extraction_mode,
                    "file_data": read_backend_file_data(backend, candidate_paths[0]),
                    "grep_matches": raw_matches,
                    "glob_matches": glob_backend_matches(backend, "**/*.md", route_prefix, settings.raw_backend_max_matches),
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