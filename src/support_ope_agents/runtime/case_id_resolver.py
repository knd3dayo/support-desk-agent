from __future__ import annotations

import re
from uuid import uuid4


class CaseIdResolverTool:
    def __init__(self):
        self._patterns = (
            re.compile(r"\b(CASE[-_][A-Za-z0-9-]+)\b", re.IGNORECASE),
            re.compile(r"\b([A-Z]{2,10}-\d{2,})\b"),
            re.compile(r"(?:問い合わせ番号|ケースID|case_id)\s*[:：]\s*([A-Za-z0-9_-]+)", re.IGNORECASE),
        )

    def resolve(self, prompt: str, explicit_case_id: str | None = None) -> str:
        if explicit_case_id:
            return explicit_case_id

        for pattern in self._patterns:
            match = pattern.search(prompt)
            if match:
                return match.group(1).upper()

        return f"CASE-{uuid4().hex.upper()}"