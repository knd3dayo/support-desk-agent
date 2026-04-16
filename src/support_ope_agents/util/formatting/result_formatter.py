from __future__ import annotations

import json
from typing import Any


def format_result(result: Any) -> str:
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str)
    if isinstance(result, (dict, list)):
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return str(result)