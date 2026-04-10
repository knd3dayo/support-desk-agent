from __future__ import annotations

import json
from typing import Any

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools.document_renderer import render_document_payload
from support_ope_agents.tools.shared_memory_payload import MemoryWriteMode, SharedMemoryDocumentPayload, SharedMemorySectionPayload


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
            rendered = render_document_payload(content)
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