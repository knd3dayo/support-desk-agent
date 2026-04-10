from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4


CASE_ID_FILENAME = ".support-ope-case-id"


class CaseIdResolverService:
    def __init__(self):
        self._patterns = (
            re.compile(r"\b(CASE[-_][A-Za-z0-9-]+)\b", re.IGNORECASE),
            re.compile(r"\b([A-Z]{2,10}-\d{2,})\b"),
            re.compile(r"(?:問い合わせ番号|ケースID|case_id)\s*[:：]\s*([A-Za-z0-9_-]+)", re.IGNORECASE),
        )

    @staticmethod
    def _normalize_trace_id(trace_id: str | None) -> str:
        if not trace_id:
            return f"TRACE-{uuid4().hex}"
        normalized = trace_id.strip()
        if normalized.startswith("TRACE-"):
            return normalized
        if normalized.startswith("SESSION-"):
            return f"TRACE-{normalized.removeprefix('SESSION-')}"
        return f"TRACE-{normalized}"

    @staticmethod
    def _normalize_ticket_id(value: str) -> str:
        return value.strip().upper()

    def resolve_external_ticket_id(self, *, explicit_ticket_id: str | None = None, trace_id: str | None = None) -> str:
        if explicit_ticket_id:
            return self._normalize_ticket_id(explicit_ticket_id)
        return f"EXT-{self._normalize_trace_id(trace_id)}"

    def resolve_internal_ticket_id(self, *, explicit_ticket_id: str | None = None, trace_id: str | None = None) -> str:
        if explicit_ticket_id:
            return self._normalize_ticket_id(explicit_ticket_id)
        return f"INT-{self._normalize_trace_id(trace_id)}"

    def resolve(self, prompt: str, explicit_case_id: str | None = None, workspace_path: str | None = None) -> str:
        if explicit_case_id:
            return explicit_case_id

        if workspace_path:
            marker_path = Path(workspace_path).expanduser().resolve() / CASE_ID_FILENAME
            if marker_path.exists():
                value = marker_path.read_text(encoding="utf-8").strip()
                if value:
                    return value.upper()

        for pattern in self._patterns:
            match = pattern.search(prompt)
            if match:
                return match.group(1).upper()

        return f"CASE-{uuid4().hex.upper()}"