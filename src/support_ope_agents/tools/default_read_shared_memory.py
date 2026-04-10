from __future__ import annotations

import json

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore


def build_default_read_shared_memory_tool(config: AppConfig):
    memory_store = CaseMemoryStore(config)

    async def read_shared_memory(case_id: str, workspace_path: str) -> str:
        case_paths = memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
        result = {
            "context": memory_store.read_text(case_paths.shared_context),
            "progress": memory_store.read_text(case_paths.shared_progress),
            "summary": memory_store.read_text(case_paths.shared_summary),
            "context_path": str(case_paths.shared_context),
            "progress_path": str(case_paths.shared_progress),
            "summary_path": str(case_paths.shared_summary),
        }
        return json.dumps(result, ensure_ascii=False)

    return read_shared_memory