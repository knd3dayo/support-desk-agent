from __future__ import annotations

import json

from support_ope_agents.config.models import AppConfig

from .document_source_search import load_ignore_patterns, search_document_sources


def build_default_search_documents_tool(config: AppConfig):
    settings = config.agents.KnowledgeRetrieverAgent
    ignore_patterns = load_ignore_patterns(settings.ignore_patterns, settings.ignore_patterns_file)

    def _search_documents(*, query: str = "") -> str:
        payload = search_document_sources(
            document_sources=settings.document_sources,
            ignore_patterns=ignore_patterns,
            query=query,
            unavailable_message="参照可能なドキュメントがないので回答できません。agents.KnowledgeRetrieverAgent.document_sources を設定してください。",
            route_base="knowledge",
            source_type="document_source",
            evidence_keywords=["アーキテクチャ", "生成AI", "Application層", "Tool層", "AIガバナンス層"],
        )
        return json.dumps(payload, ensure_ascii=False)

    return _search_documents