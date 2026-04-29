from __future__ import annotations

import re


def derive_case_title(raw_issue: str, *, fallback: str = "新規ケース", max_length: int = 72) -> str:
    cleaned_lines: list[str] = []
    for raw_line in raw_issue.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line.startswith("```"):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*+]\s*", "", line)
        line = re.sub(r"^\[(additional customer input|追加情報)\]\s*", "", line, flags=re.IGNORECASE)
        line = line.strip("-:> ")
        if line:
            cleaned_lines.append(line)

    for line in cleaned_lines:
        if _looks_like_title(line):
            return _truncate_title(line, max_length=max_length)

    if cleaned_lines:
        return _truncate_title(cleaned_lines[0], max_length=max_length)
    return fallback


def _looks_like_title(line: str) -> bool:
    lowered = line.lower()
    if lowered in {"概要", "summary", "背景", "background", "details"}:
        return False
    if line.startswith("CASE-") and len(line.split()) == 1:
        return False
    return True


def _truncate_title(value: str, *, max_length: int) -> str:
    normalized = value.strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."