from __future__ import annotations

import json
from typing import Any


def format_result(result: Any) -> str:
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str)
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return str(result)


def format_ticket_context(state: dict) -> str:
    """
    intake_ticket_context_summary を整形して返す共通ユーティリティ。
    """
    ticket_context = state.get("intake_ticket_context_summary") or {}
    if not ticket_context:
        return ""

    labels = {
        "external_ticket": "外部チケット要約",
        "internal_ticket": "内部チケット要約",
        "external_ticket_attachments": "外部チケット添付",
        "internal_ticket_attachments": "内部チケット添付",
    }
    lines = [
        f"- {labels.get(key, key)}: {str(value).strip()}"
        for key, value in ticket_context.items()
        if str(value).strip()
    ]
    if not lines:
        return ""
    return "取得済みチケット文脈:\n" + "\n".join(lines)