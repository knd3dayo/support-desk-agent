from __future__ import annotations

import json

from support_ope_agents.config.models import AppConfig

from .document_source_backend import (
    build_document_source_backend,
    candidate_virtual_paths_for_source,
    extract_feature_bullets,
    extract_relevant_snippet,
    grep_backend_evidence,
    load_ignore_patterns,
    read_backend_content,
)


def build_default_search_documents_tool(config: AppConfig):
    settings = config.agents.KnowledgeRetrieverAgent
    ignore_patterns = load_ignore_patterns(settings.ignore_patterns, settings.ignore_patterns_file)

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

        results: list[dict[str, object]] = []
        for source in settings.document_sources:
            route_prefix = f"/knowledge/{source.name}/"
            candidate_paths = candidate_virtual_paths_for_source(
                backend=backend,
                source=source,
                route_base="knowledge",
                ignore_patterns=ignore_patterns,
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

            primary_content = read_backend_content(backend, candidate_paths[0])[:8000]
            results.append(
                {
                    "source_name": source.name,
                    "source_description": source.description,
                    "source_type": "document_source",
                    "status": "matched",
                    "summary": extract_relevant_snippet(primary_content, query) or f"{source.name} から関連箇所を抽出しました。",
                    "path": str(source.path),
                    "route_prefix": route_prefix,
                    "matched_paths": candidate_paths[:3],
                    "evidence": grep_backend_evidence(
                        backend,
                        query,
                        route_prefix,
                        extra_keywords=["アーキテクチャ", "生成AI", "Application層", "Tool層", "AIガバナンス層"],
                    ),
                    "feature_bullets": extract_feature_bullets(primary_content, query),
                }
            )

        payload = {
            "status": "matched",
            "message": "document_sources から概要候補を抽出しました。",
            "query": query,
            "results": results,
        }
        return json.dumps(payload, ensure_ascii=False)

    return _search_documents