from __future__ import annotations

import json

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore


def build_default_read_working_memory_tool(config: AppConfig, agent_name: str):
    memory_store = CaseMemoryStore(config)

    async def read_working_memory(case_id: str, workspace_path: str) -> str:
        working_file = memory_store.resolve_existing_working_memory(
            case_id,
            agent_name,
            workspace_path=workspace_path,
        )
        return json.dumps(
            {
                "agent_name": agent_name,
                "working_memory_path": str(working_file),
                "content": memory_store.read_text(working_file),
            },
            ensure_ascii=False,
        )

    return read_working_memory