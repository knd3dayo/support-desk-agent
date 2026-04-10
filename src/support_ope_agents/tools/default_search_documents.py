from __future__ import annotations

import json
import re
from pathlib import Path

from support_ope_agents.config.models import AppConfig


def _candidate_files(source_path: Path) -> list[Path]:
    if source_path.is_file():
        return [source_path]
    if not source_path.exists() or not source_path.is_dir():
        return []

    ignored_parts = {".git", ".venv", "venv", "node_modules", "site-packages", ".pytest_cache", "__pycache__"}
    candidates = [
        path
        for path in source_path.rglob("*.md")
        if path.is_file() and not any(part.startswith(".") or part in ignored_parts for part in path.relative_to(source_path).parts)
    ]

    def _score(path: Path) -> tuple[int, int, str]:
        normalized = path.as_posix().lower()
        score = 0
        depth = len(path.relative_to(source_path).parts)
        if path.name.lower() == "readme.md":
            score += 100
        if "アーキテクチャ" in path.as_posix():
            score += 60
        if "architecture" in normalized:
            score += 60
        if "はじめに" in path.as_posix():
            score += 30
        if "概要" in path.as_posix():
            score += 20
        if "/docs/" in normalized:
            score += 10
        return (-score, depth, normalized)

    return sorted(candidates, key=_score)[:5]


def _extract_summary(content: str) -> str:
    paragraphs = [block.strip().replace("\n", " ") for block in re.split(r"\n\s*\n", content) if block.strip()]
    filtered = [paragraph for paragraph in paragraphs if not paragraph.startswith("#")]
    summary_parts: list[str] = []

    for paragraph in filtered:
        if len(paragraph) >= 40:
            summary_parts.append(paragraph)
            break

    layered = next(
        (
            paragraph
            for paragraph in filtered
            if "Application層" in paragraph and "Tool層" in paragraph and "AIガバナンス層" in paragraph
        ),
        "",
    )
    if layered and layered not in summary_parts:
        summary_parts.append(layered)

    if not summary_parts:
        return ""
    return " ".join(summary_parts)[:600]


def _extract_evidence(content: str, query: str) -> list[str]:
    query_tokens = [token for token in re.split(r"[\s/,:()]+", query) if len(token) >= 2]
    keywords = [*query_tokens, "アーキテクチャ", "生成AI", "Application層", "Tool層", "AIガバナンス層"]
    evidence: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(keyword in stripped for keyword in keywords):
            evidence.append(stripped)
        if len(evidence) >= 3:
            break
    return evidence


def _virtual_path(source_name: str, source_root: Path, candidate: Path) -> str:
    if source_root.is_file():
        return f"/knowledge/{source_name}/{candidate.name}"
    relative = candidate.relative_to(source_root).as_posix()
    return f"/knowledge/{source_name}/{relative}"


def build_default_search_documents_tool(config: AppConfig):
    def _search_documents(*, query: str = "") -> str:
        document_sources = config.knowledge_retrieval.document_sources
        if not document_sources:
            return json.dumps(
                {
                    "status": "unavailable",
                    "message": "参照可能なドキュメントがないので回答できません。knowledge_retrieval.document_sources を設定してください。",
                    "query": query,
                    "results": [],
                },
                ensure_ascii=False,
            )

        results = []
        for source in document_sources:
            source_path = Path(source.path).expanduser().resolve()
            candidates = _candidate_files(source_path)
            if not candidates:
                results.append(
                    {
                        "source_name": source.name,
                        "source_description": source.description,
                        "source_type": "document_source",
                        "status": "unavailable",
                        "summary": "参照対象パスに概要取得可能な Markdown 文書が見つかりません。",
                        "path": str(source.path),
                        "route_prefix": f"/knowledge/{source.name}/",
                        "matched_paths": [],
                        "evidence": [],
                    }
                )
                continue

            primary_content = candidates[0].read_text(encoding="utf-8", errors="ignore")[:8000]
            summary = _extract_summary(primary_content) or f"{source.name} から概要候補を抽出しました。"
            matched_paths = [_virtual_path(source.name, source_path, candidate) for candidate in candidates[:3]]
            evidence = _extract_evidence(primary_content, query)
            results.append(
                {
                    "source_name": source.name,
                    "source_description": source.description,
                    "source_type": "document_source",
                    "status": "matched",
                    "summary": summary,
                    "path": str(source.path),
                    "route_prefix": f"/knowledge/{source.name}/",
                    "matched_paths": matched_paths,
                    "evidence": evidence,
                }
            )

        return json.dumps(
            {
                "status": "matched",
                "message": "document_sources から概要候補を抽出しました。",
                "query": query,
                "results": results,
            },
            ensure_ascii=False,
        )

    return _search_documents