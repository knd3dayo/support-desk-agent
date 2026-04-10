from __future__ import annotations

import json
from typing import Any

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools.shared_memory_payload import MemoryWriteMode, SharedMemoryDocumentPayload, SharedMemorySectionPayload


def _render_payload(payload: Any, *, default_heading_level: int = 1) -> str:
    if payload is None:
        return ""
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
        document_payload = payload
        title = document_payload.get("title")
        if isinstance(title, str) and title.strip():
            heading_level = int(document_payload.get("heading_level", default_heading_level))
            lines.append(f"{'#' * max(1, heading_level)} {title.strip()}")
            lines.append("")

        summary = document_payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(summary.strip())
            lines.append("")

        bullets = document_payload.get("bullets")
        if isinstance(bullets, list):
            for bullet in bullets:
                lines.append(f"- {str(bullet)}")

        sections = document_payload.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    lines.append(f"- {json.dumps(section, ensure_ascii=False)}")
                    continue
                typed_section: SharedMemorySectionPayload = section
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


def build_default_write_shared_memory_tool(config: AppConfig):
    memory_store = CaseMemoryStore(config)

    async def write_shared_memory(
        case_id: str,
        workspace_path: str,
        context_content: str | SharedMemoryDocumentPayload | list[str] | None = None,
        progress_content: str | SharedMemoryDocumentPayload | list[str] | None = None,
        summary_content: str | SharedMemoryDocumentPayload | list[str] | None = None,
        mode: MemoryWriteMode = "replace",
    ) -> str:
        case_paths = memory_store.initialize_case(case_id, workspace_path=workspace_path)

        def _write(path, content: Any) -> str | None:
            if content is None:
                return None
            rendered = _render_payload(content)
            if not rendered.strip():
                return None
            normalized = rendered if rendered.endswith("\n") else rendered + "\n"
            if mode == "append":
                memory_store.append_text(path, normalized)
            else:
                path.write_text(normalized, encoding="utf-8")
            return str(path)

        result = {
            "mode": mode,
            "context_path": _write(case_paths.shared_context, context_content),
            "progress_path": _write(case_paths.shared_progress, progress_content),
            "summary_path": _write(case_paths.shared_summary, summary_content),
        }
        return json.dumps(result, ensure_ascii=False)

    return write_shared_memory