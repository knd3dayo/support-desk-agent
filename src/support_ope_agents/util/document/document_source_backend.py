from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Protocol, Sequence

from support_ope_agents.util.deep_agents_extension import FilteredFilesystemBackend

try:
    from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
except Exception:  # pragma: no cover
    CompositeBackend = None
    FilesystemBackend = None
    StateBackend = None


class DocumentSourceLike(Protocol):
    name: str
    description: str
    path: Path


DEFAULT_DOCUMENT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".git",
    ".git/**",
    ".venv",
    ".venv/**",
    "**/.git",
    "**/.git/**",
    "**/.venv",
    "**/.venv/**",
    "__pycache__",
    "__pycache__/**",
    "**/__pycache__",
    "**/__pycache__/**",
    ".pytest_cache",
    ".pytest_cache/**",
    "**/.pytest_cache",
    "**/.pytest_cache/**",
    "site-packages",
    "site-packages/**",
    "**/site-packages",
    "**/site-packages/**",
    "node_modules",
    "node_modules/**",
    "**/node_modules",
    "**/node_modules/**",
)


def default_document_ignore_patterns() -> tuple[str, ...]:
    return DEFAULT_DOCUMENT_IGNORE_PATTERNS


def build_document_source_backend(
    *,
    document_sources: Sequence[DocumentSourceLike],
    route_base: str,
) -> Any | None:
    if CompositeBackend is None or FilesystemBackend is None or StateBackend is None:
        return None

    routes: dict[str, Any] = {}
    normalized_route_base = route_base.strip("/")
    for source in document_sources:
        source_path = Path(source.path).expanduser().resolve()
        route_prefix = f"/{normalized_route_base}/{source.name}/"
        routes[route_prefix] = FilesystemBackend(root_dir=str(source_path), virtual_mode=True)

    if not routes:
        return None

    return CompositeBackend(default=StateBackend(), routes=routes)


def build_filtered_document_source_backend(
    *,
    document_sources: Sequence[DocumentSourceLike],
    route_base: str,
    ignore_patterns: Sequence[str] | None = None,
) -> Any | None:
    if CompositeBackend is None or StateBackend is None:
        return None

    effective_ignore_patterns = tuple(ignore_patterns or default_document_ignore_patterns())
    routes: dict[str, Any] = {}
    normalized_route_base = route_base.strip("/")
    for source in document_sources:
        source_path = Path(source.path).expanduser().resolve()
        route_prefix = f"/{normalized_route_base}/{source.name}/"
        routes[route_prefix] = FilteredFilesystemBackend(
            root_dir=str(source_path),
            virtual_mode=True,
            ignore_patterns=effective_ignore_patterns,
        )

    if not routes:
        return None

    return CompositeBackend(default=StateBackend(), routes=routes)


def describe_document_source_backend(
    *,
    document_sources: Sequence[DocumentSourceLike],
    route_base: str,
) -> dict[str, object] | None:
    if not document_sources:
        return None
    normalized_route_base = route_base.strip("/")
    return {
        "type": "CompositeBackend",
        "default": "StateBackend",
        "routes": {
            f"/{normalized_route_base}/{source.name}/": str(Path(source.path).expanduser().resolve())
            for source in document_sources
        },
    }


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


def is_ignored_relative_path(relative_path: str, ignore_patterns: list[str]) -> bool:
    return any(matches_ignore_pattern(relative_path, pattern) for pattern in ignore_patterns)


def score_relative_markdown_path(relative_path: str) -> tuple[int, int, str]:
    normalized = relative_path.lower()
    score = 0
    depth = len(Path(relative_path).parts)
    name = Path(relative_path).name.lower()
    if name == "readme.md":
        score += 100
    if "アーキテクチャ" in relative_path:
        score += 60
    if "architecture" in normalized:
        score += 60
    if "guideline" in normalized or "policy" in normalized or "規定" in relative_path or "ガイドライン" in relative_path:
        score += 80
    if "law" in normalized or "法令" in relative_path:
        score += 80
    if "はじめに" in relative_path:
        score += 30
    if "概要" in relative_path:
        score += 20
    if "/docs/" in normalized or normalized.startswith("docs/"):
        score += 10
    return (-score, depth, normalized)


def extract_relevant_snippet(content: str, query: str) -> str:
    return extract_relevant_snippet_with_limit(content, query, max_chars=600)


def extract_relevant_snippet_with_limit(content: str, query: str, max_chars: int | None) -> str:
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
    filtered = [paragraph for paragraph in paragraphs if not paragraph.startswith("#")]
    query_tokens = [token for token in re.split(r"[\s/,:()]+", query.lower()) if len(token) >= 2]

    for paragraph in filtered:
        normalized = paragraph.lower()
        if query_tokens and any(token in normalized for token in query_tokens):
            return paragraph if max_chars is None else paragraph[:max_chars]

    for paragraph in filtered:
        if len(paragraph) >= 20:
            return paragraph if max_chars is None else paragraph[:max_chars]

    if not filtered:
        return ""
    return filtered[0] if max_chars is None else filtered[0][:max_chars]


def extract_feature_bullets(content: str, query: str) -> list[str]:
    return extract_feature_bullets_with_options(content, query, require_query_match=True, heading_keywords=None, max_items=5)


def extract_feature_bullets_with_options(
    content: str,
    query: str,
    *,
    require_query_match: bool,
    heading_keywords: list[str] | None,
    max_items: int | None,
) -> list[str]:
    normalized_query = query.lower()
    if require_query_match and not any(token in normalized_query for token in ["機能", "一覧", "できること", "features", "feature"]):
        return []

    section_heading_keywords = [keyword.lower() for keyword in (heading_keywords or ["できること", "主な機能", "よく使う入口", "features"])]
    lines = content.splitlines()
    bullets: list[str] = []
    capturing = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if capturing and bullets:
                break
            continue
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            if any(keyword in heading for keyword in section_heading_keywords):
                capturing = True
                continue
            if capturing and bullets:
                break
            capturing = False
            continue
        if capturing and stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
            if max_items is not None and len(bullets) >= max_items:
                break

    return bullets


def read_backend_file_data(backend: Any, path: str) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        result = backend.read(path)
    except Exception:
        return None
    file_data = getattr(result, "file_data", None)
    if not isinstance(file_data, dict):
        return None
    return dict(file_data)


def read_backend_content(backend: Any, path: str) -> str:
    file_data = read_backend_file_data(backend, path)
    if not isinstance(file_data, dict):
        return ""
    return str(file_data.get("content") or "")


def read_backend_content_with_limit(backend: Any, path: str, char_limit: int | None) -> str:
    content = read_backend_content(backend, path)
    if char_limit is None:
        return content
    return content[:char_limit]


def grep_backend_matches(
    backend: Any,
    query: str,
    path: str,
    extra_keywords: list[str] | None = None,
    max_items: int | None = 3,
    ignore_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    query_tokens = [token for token in re.split(r"[\s/,:()]+", query) if len(token) >= 2]
    keywords = [*query_tokens, *(extra_keywords or [])]
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    normalized_base_path = path.rstrip("/") + "/"
    for keyword in keywords:
        try:
            grep_result = backend.grep(keyword, path=path)
        except Exception:
            continue
        for match in list(getattr(grep_result, "matches", None) or []):
            if not isinstance(match, dict):
                continue
            line_no = int(match.get("line") or 0)
            key = (str(match.get("path") or ""), line_no)
            text = str(match.get("text") or "").strip()
            if not text or key in seen:
                continue
            candidate_path = str(match.get("path") or "").strip()
            if ignore_patterns:
                relative_path = candidate_path.removeprefix(normalized_base_path) if candidate_path.startswith(normalized_base_path) else candidate_path
                if relative_path and is_ignored_relative_path(relative_path, ignore_patterns):
                    continue
            seen.add(key)
            matches.append(dict(match))
            if max_items is not None and len(matches) >= max_items:
                return matches
    return matches


def grep_backend_evidence(backend: Any, query: str, path: str, extra_keywords: list[str] | None = None) -> list[str]:
    return grep_backend_evidence_with_limit(backend, query, path, extra_keywords=extra_keywords, max_items=3)


def grep_backend_evidence_with_limit(
    backend: Any,
    query: str,
    path: str,
    extra_keywords: list[str] | None = None,
    max_items: int | None = 3,
    ignore_patterns: list[str] | None = None,
) -> list[str]:
    return [
        str(match.get("text") or "").strip()
        for match in grep_backend_matches(
            backend,
            query,
            path,
            extra_keywords=extra_keywords,
            max_items=max_items,
            ignore_patterns=ignore_patterns,
        )
    ]


def glob_backend_matches(
    backend: Any,
    pattern: str,
    path: str,
    max_items: int | None = None,
    ignore_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    glob_result = backend.glob(pattern, path=path)
    normalized_base_path = path.rstrip("/") + "/"
    matches: list[dict[str, Any]] = []
    for match in list(getattr(glob_result, "matches", None) or []):
        if not isinstance(match, dict):
            continue
        candidate_path = str(match.get("path") or "").strip()
        if ignore_patterns:
            relative_path = candidate_path.removeprefix(normalized_base_path) if candidate_path.startswith(normalized_base_path) else candidate_path
            if relative_path and is_ignored_relative_path(relative_path, ignore_patterns):
                continue
        matches.append(dict(match))
    if max_items is None:
        return matches
    return matches[:max_items]


def candidate_virtual_paths_for_source(
    *,
    backend: Any,
    source: DocumentSourceLike,
    route_base: str,
    ignore_patterns: list[str],
    limit: int | None = 5,
) -> list[str]:
    normalized_route_base = route_base.strip("/")
    route_prefix = f"/{normalized_route_base}/{source.name}/"
    source_path = Path(source.path).expanduser().resolve()

    if source_path.is_file():
        relative_path = source_path.name
        if is_ignored_relative_path(relative_path, ignore_patterns):
            return []
        return [f"{route_prefix}{relative_path}"]

    glob_result = backend.glob("**/*.md", path=route_prefix)
    matches = list(getattr(glob_result, "matches", None) or [])
    candidates: list[tuple[str, str]] = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        if bool(match.get("is_dir")):
            continue
        candidate_path = str(match.get("path") or "").strip()
        if not candidate_path.startswith(route_prefix):
            continue
        relative_path = candidate_path.removeprefix(route_prefix)
        if not relative_path or is_ignored_relative_path(relative_path, ignore_patterns):
            continue
        candidates.append((candidate_path, relative_path))

    ranked = sorted(candidates, key=lambda item: score_relative_markdown_path(item[1]))
    ordered_paths = [virtual_path for virtual_path, _ in ranked]
    if limit is None:
        return ordered_paths
    return ordered_paths[:limit]