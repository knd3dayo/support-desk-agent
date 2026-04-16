from __future__ import annotations

import json
from typing import Any

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools.document_renderer import render_document_payload
from support_ope_agents.util.shared_memory_payload import MemoryWriteMode, SharedMemoryDocumentPayload


def build_default_write_working_memory_tool(config: AppConfig, agent_name: str):
    memory_store = CaseMemoryStore(config)

    async def write_working_memory(
        case_id: str,
        workspace_path: str,
        content: str | SharedMemoryDocumentPayload | list[str] | None = None,
        mode: MemoryWriteMode = "append",
    ) -> str:
        working_file = memory_store.ensure_agent_working_memory(case_id, agent_name, workspace_path=workspace_path)
        rendered = render_document_payload(content, default_heading_level=2)
        if rendered.strip():
            normalized = rendered if rendered.endswith("\n") else rendered + "\n"
            if mode == "append":
                memory_store.append_text(working_file, normalized)
            else:
                working_file.write_text(normalized, encoding="utf-8")
        return json.dumps(
            {
                "mode": mode,
                "agent_name": agent_name,
                "working_memory_path": str(working_file),
            },
            ensure_ascii=False,
        )

    return write_working_memory