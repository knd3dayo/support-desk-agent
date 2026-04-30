from __future__ import annotations

import json

from support_desk_agent.config.models import AppConfig
from support_desk_agent.tools.document_renderer import render_document_payload
from support_desk_agent.util.shared_memory_payload import MemoryWriteMode, SharedMemoryDocumentPayload
from support_desk_agent.workspace import CaseMemoryStore


def build_default_write_draft_tool(config: AppConfig, draft_name: str):
    workspace_store = CaseMemoryStore(config)

    async def write_draft(
        case_id: str,
        workspace_path: str,
        content: str | SharedMemoryDocumentPayload | list[str] | None = None,
        mode: MemoryWriteMode = "replace",
    ) -> str:
        case_paths = workspace_store.initialize_case(case_id, workspace_path=workspace_path)
        drafts_dir = case_paths.artifacts_dir / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        draft_path = drafts_dir / f"{draft_name}.md"
        rendered = render_document_payload(content)
        if rendered.strip():
            normalized = rendered if rendered.endswith("\n") else rendered + "\n"
            if mode == "append":
                workspace_store.append_text(draft_path, normalized)
            else:
                draft_path.write_text(normalized, encoding="utf-8")
        return json.dumps(
            {
                "mode": mode,
                "draft_name": draft_name,
                "draft_path": str(draft_path),
            },
            ensure_ascii=False,
        )

    return write_draft