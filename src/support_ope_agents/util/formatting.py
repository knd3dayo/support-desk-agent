import json
from typing import Any, Dict

def parse_memory(raw_result: str) -> Dict[str, str]:
    """
    JSON文字列から context, progress, summary を抽出して返す共通ユーティリティ。
    """
    try:
        parsed = json.loads(raw_result)
    except json.JSONDecodeError:
        return {"context": "", "progress": "", "summary": ""}
    if not isinstance(parsed, dict):
        return {"context": "", "progress": "", "summary": ""}
    return {
        "context": str(parsed.get("context") or ""),
        "progress": str(parsed.get("progress") or ""),
        "summary": str(parsed.get("summary") or ""),
    }


