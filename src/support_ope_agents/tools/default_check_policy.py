from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig

from .document_source_backend import (
    build_document_source_backend,
    candidate_virtual_paths_for_source,
    extract_relevant_snippet,
    grep_backend_evidence,
    load_ignore_patterns,
    read_backend_content,
)


RISKY_EXPRESSIONS = [
    "必ず",
    "絶対に",
    "100%",
    "保証します",
    "問題ありません",
]


def _get_chat_model(config: AppConfig) -> ChatOpenAI | None:
    if config.llm.provider.lower() != "openai":
        return None
    if not config.llm.api_key:
        return None
    if str(config.llm.api_key).strip().lower() in {"dummy", "test", "placeholder"}:
        return None
    return ChatOpenAI(
        model=config.llm.model,
        api_key=cast(Any, config.llm.api_key),
        base_url=config.llm.base_url,
        temperature=0,
    )


def _stringify_response_content(content: Any) -> str:
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


def build_default_check_policy_tool(config: AppConfig):
    settings = config.agents.ComplianceReviewerAgent
    ignore_patterns = load_ignore_patterns(settings.ignore_patterns, settings.ignore_patterns_file)

    async def _check_policy(*, draft_response: str = "", review_focus: str = "") -> str:
        query = "\n".join(part for part in [review_focus.strip(), draft_response.strip()] if part).strip()
        if not settings.document_sources:
            search_result = {
                "status": "unavailable",
                "message": (
                    "参照可能なポリシー文書がないため、社内規定・ガイドライン・法令との照合結果を返せません。"
                    " agents.ComplianceReviewerAgent.document_sources を設定してください。"
                ),
                "query": query,
                "results": [],
            }
        else:
            backend = build_document_source_backend(document_sources=settings.document_sources, route_base="policy")
            if backend is None:
                search_result = {
                    "status": "unavailable",
                    "message": (
                        "参照可能なポリシー文書がないため、社内規定・ガイドライン・法令との照合結果を返せません。"
                        " agents.ComplianceReviewerAgent.document_sources を設定してください。 DeepAgents backend を初期化できませんでした。"
                    ),
                    "query": query,
                    "results": [],
                }
            else:
                results: list[dict[str, object]] = []
                for source in settings.document_sources:
                    route_prefix = f"/policy/{source.name}/"
                    candidate_paths = candidate_virtual_paths_for_source(
                        backend=backend,
                        source=source,
                        route_base="policy",
                        ignore_patterns=ignore_patterns,
                    )
                    if not candidate_paths:
                        results.append(
                            {
                                "source_name": source.name,
                                "source_description": source.description,
                                "source_type": "policy_source",
                                "status": "unavailable",
                                "summary": "参照対象パスに概要取得可能な Markdown 文書が見つかりません。",
                                "path": str(source.path),
                                "route_prefix": route_prefix,
                                "matched_paths": [],
                                "evidence": [],
                            }
                        )
                        continue

                    primary_content = read_backend_content(backend, candidate_paths[0])[:8000]
                    results.append(
                        {
                            "source_name": source.name,
                            "source_description": source.description,
                            "source_type": "policy_source",
                            "status": "matched",
                            "summary": extract_relevant_snippet(primary_content, query) or f"{source.name} から関連箇所を抽出しました。",
                            "path": str(source.path),
                            "route_prefix": route_prefix,
                            "matched_paths": candidate_paths[:3],
                            "evidence": grep_backend_evidence(
                                backend,
                                query,
                                route_prefix,
                                extra_keywords=["規定", "ガイドライン", "法令", "注意", "免責", "生成AI"],
                            ),
                        }
                    )
                search_result = {
                    "status": "matched",
                    "message": "document_sources から概要候補を抽出しました。",
                    "query": query,
                    "results": results,
                }

        issues: list[str] = []
        notice_phrases = [phrase.strip() for phrase in settings.notice.required_phrases if phrase.strip()]
        notice_present = any(phrase in draft_response for phrase in notice_phrases)
        matched_notice_phrase = ""
        if settings.notice.required:
            if notice_present:
                matched_notice_phrase = next(phrase for phrase in notice_phrases if phrase in draft_response)
            else:
                issues.append("注意文が不足しています。少なくとも「生成AIは誤った回答をすることがあります」相当の注意書きを含めてください。")
        elif notice_present:
            matched_notice_phrase = next(phrase for phrase in notice_phrases if phrase in draft_response)

        for expression in RISKY_EXPRESSIONS:
            if expression in draft_response:
                issues.append(f"断定的な表現 '{expression}' が含まれています。根拠に即した限定表現へ修正してください。")

        raw_results = search_result.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        matched_policy_sources = [
            str(item.get("source_name") or "")
            for item in results
            if isinstance(item, dict) and str(item.get("status") or "") == "matched"
        ]
        if not matched_policy_sources:
            issues.append("確認根拠となるポリシー文書を取得できませんでした。document_sources の設定と配置を確認してください。")

        llm_review_summary = ""
        model = _get_chat_model(config)
        if model is not None:
            policy_summaries = [
                {
                    "source_name": str(item.get("source_name") or ""),
                    "summary": str(item.get("summary") or ""),
                    "evidence": list(item.get("evidence") or []),
                }
                for item in results
                if isinstance(item, dict)
            ]
            prompt = {
                "task": "Review the draft for factual alignment, policy compliance, and expression risks.",
                "review_focus": review_focus,
                "draft_response": draft_response,
                "required_notice_phrases": notice_phrases,
                "policy_sources": policy_summaries,
                "output_format": {
                    "summary": "short string",
                    "issues": ["string"],
                },
            }
            try:
                response = await model.ainvoke(
                    [
                        HumanMessage(
                            content=(
                                "Return JSON only. Check factual consistency, policy compliance, and unsafe wording.\n"
                                + json.dumps(prompt, ensure_ascii=False)
                            )
                        )
                    ]
                )
                content = _stringify_response_content(response.content)
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    llm_review_summary = str(parsed.get("summary") or "").strip()
                    llm_issues = [str(item).strip() for item in list(parsed.get("issues") or []) if str(item).strip()]
                    for issue in llm_issues:
                        if issue not in issues:
                            issues.append(issue)
            except Exception:
                llm_review_summary = ""

        status = "passed" if not issues else "revision_required"
        review_summary = (
            "ドラフトはポリシー照合と注意文チェックを通過しました。"
            if status == "passed" and settings.notice.required
            else "ドラフトはポリシー照合を通過しました。"
            if status == "passed"
            else "ドラフトはポリシー照合または注意文チェックで修正が必要です。"
            if settings.notice.required
            else "ドラフトはポリシー照合で修正が必要です。"
        )
        if llm_review_summary:
            review_summary = f"{review_summary} {llm_review_summary}".strip()
        payload = {
            "status": status,
            "message": review_summary,
            "review_focus": review_focus,
            "results": results,
            "adopted_sources": matched_policy_sources,
            "issues": issues,
            "notice_check": {
                "required": settings.notice.required,
                "present": notice_present,
                "matched_phrase": matched_notice_phrase,
                "required_phrases": notice_phrases,
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    return _check_policy