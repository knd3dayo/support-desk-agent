from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Protocol


class DocumentSourceLike(Protocol):
    name: str
    description: str
    path: Path


def load_ignore_patterns(ignore_patterns: list[str], ignore_patterns_file: Path | None) -> list[str]:
    patterns = [pattern.strip() for pattern in ignore_patterns if pattern.strip()]
    if ignore_patterns_file is None or not ignore_patterns_file.exists():
        return patterns

    for line in ignore_patterns_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def matches_ignore_pattern(relative_path: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip().replace("\\", "/")
    if not normalized_pattern:
        return False
    if normalized_pattern.endswith("/"):
        normalized_pattern = f"{normalized_pattern}**"
    return fnmatch.fnmatchcase(relative_path, normalized_pattern)


def is_ignored_path(source_path: Path, candidate: Path, ignore_patterns: list[str]) -> bool:
    relative_path = candidate.relative_to(source_path).as_posix()
    return any(matches_ignore_pattern(relative_path, pattern) for pattern in ignore_patterns)


def candidate_files(source_path: Path, ignore_patterns: list[str]) -> list[Path]:
    if source_path.is_file():
        if _is_single_file_ignored(source_path, ignore_patterns):
            return []
        return [source_path]
    if not source_path.exists() or not source_path.is_dir():
        return []

    candidates = [
        path
        for path in source_path.rglob("*.md")
        if path.is_file() and not is_ignored_path(source_path, path, ignore_patterns)
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
        if "guideline" in normalized or "policy" in normalized or "規定" in path.as_posix() or "ガイドライン" in path.as_posix():
            score += 80
        if "law" in normalized or "法令" in path.as_posix():
            score += 80
        if "はじめに" in path.as_posix():
            score += 30
        if "概要" in path.as_posix():
            score += 20
        if "/docs/" in normalized:
            score += 10
        return (-score, depth, normalized)

    return sorted(candidates, key=_score)[:5]


def extract_summary(content: str) -> str:
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


def extract_evidence(content: str, query: str, extra_keywords: list[str] | None = None) -> list[str]:
    query_tokens = [token for token in re.split(r"[\s/,:()]+", query) if len(token) >= 2]
    keywords = [*query_tokens, *(extra_keywords or [])]
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


def virtual_path(source_name: str, source_root: Path, candidate: Path, route_base: str) -> str:
    normalized_base = route_base.strip("/")
    if source_root.is_file():
        return f"/{normalized_base}/{source_name}/{candidate.name}"
    relative = candidate.relative_to(source_root).as_posix()
    return f"/{normalized_base}/{source_name}/{relative}"


def search_document_sources(
    *,
    document_sources: list[DocumentSourceLike],
    ignore_patterns: list[str],
    query: str,
    unavailable_message: str,
    route_base: str,
    source_type: str,
    evidence_keywords: list[str] | None = None,
) -> dict[str, object]:
    if not document_sources:
        return {
            "status": "unavailable",
            "message": unavailable_message,
            "query": query,
            "results": [],
        }

    results: list[dict[str, object]] = []
    normalized_route_base = route_base.strip("/")
    for source in document_sources:
        source_path = Path(source.path).expanduser().resolve()
        candidates = candidate_files(source_path, ignore_patterns)
        if not candidates:
            results.append(
                {
                    "source_name": source.name,
                    "source_description": source.description,
                    "source_type": source_type,
                    "status": "unavailable",
                    "summary": "参照対象パスに概要取得可能な Markdown 文書が見つかりません。",
                    "path": str(source.path),
                    "route_prefix": f"/{normalized_route_base}/{source.name}/",
                    "matched_paths": [],
                    "evidence": [],
                }
            )
            continue

        primary_content = candidates[0].read_text(encoding="utf-8", errors="ignore")[:8000]
        summary = extract_summary(primary_content) or f"{source.name} から概要候補を抽出しました。"
        matched_paths = [virtual_path(source.name, source_path, candidate, normalized_route_base) for candidate in candidates[:3]]
        evidence = extract_evidence(primary_content, query, extra_keywords=evidence_keywords)
        results.append(
            {
                "source_name": source.name,
                "source_description": source.description,
                "source_type": source_type,
                "status": "matched",
                "summary": summary,
                "path": str(source.path),
                "route_prefix": f"/{normalized_route_base}/{source.name}/",
                "matched_paths": matched_paths,
                "evidence": evidence,
            }
        )

    return {
        "status": "matched",
        "message": "document_sources から概要候補を抽出しました。",
        "query": query,
        "results": results,
    }


def _is_single_file_ignored(source_path: Path, ignore_patterns: list[str]) -> bool:
    synthetic_root = source_path.parent
    return is_ignored_path(synthetic_root, source_path, ignore_patterns)