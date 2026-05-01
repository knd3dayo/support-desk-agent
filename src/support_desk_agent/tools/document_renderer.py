from __future__ import annotations

import json
from typing import Any
from typing import cast

from support_desk_agent.util.shared_memory_payload import SharedMemorySectionPayload


def render_document_payload(payload: Any, *, default_heading_level: int = 1) -> str:
    if payload is None:
        return ""
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(exclude_none=True)
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        lines: list[str] = []
        for item in payload:
            if isinstance(item, str):
                lines.append(f"- {item}")
            else:
                lines.append(f"- {json.dumps(item, ensure_ascii=False)}")
        return "\n".join(lines)
    if isinstance(payload, dict):
        lines: list[str] = []
        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            heading_level = int(payload.get("heading_level", default_heading_level))
            lines.append(f"{'#' * max(1, heading_level)} {title.strip()}")
            lines.append("")

        summary = payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(summary.strip())
            lines.append("")

        bullets = payload.get("bullets")
        if isinstance(bullets, list):
            for bullet in bullets:
                lines.append(f"- {str(bullet)}")

        sections = payload.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    lines.append(f"- {json.dumps(section, ensure_ascii=False)}")
                    continue
                typed_section = cast(SharedMemorySectionPayload, section)
                section_title = str(typed_section.get("title") or "").strip()
                if section_title:
                    if lines and lines[-1] != "":
                        lines.append("")
                    lines.append(f"## {section_title}")
                section_summary = str(typed_section.get("summary") or "").strip()
                if section_summary:
                    lines.append(section_summary)
                section_bullets = typed_section.get("bullets")
                if isinstance(section_bullets, list):
                    for bullet in section_bullets:
                        lines.append(f"- {str(bullet)}")

        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)
    return json.dumps(payload, ensure_ascii=False)