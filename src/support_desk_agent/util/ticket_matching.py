from __future__ import annotations

import re


def normalize_similarity_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", value).lower()