from __future__ import annotations

import json
from typing import Any


def build_default_request_revision_tool():
    def _request_revision(*, issues: list[str] | None = None, review_summary: str = "", draft_response: str = "") -> str:
        normalized_issues = [str(item).strip() for item in (issues or []) if str(item).strip()]
        revision_points = normalized_issues or ["レビュー結果をもとに表現と根拠を見直してください。"]
        payload: dict[str, Any] = {
            "status": "revision_required" if normalized_issues else "no_revision",
            "review_summary": review_summary,
            "revision_points": revision_points,
            "draft_excerpt": draft_response[:240],
        }
        return json.dumps(payload, ensure_ascii=False)

    return _request_revision