from __future__ import annotations

import json
from typing import Any

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore

from support_ope_agents.tools.document_renderer import render_document_payload
from support_ope_agents.util.shared_memory_payload import MemoryWriteMode, SharedMemoryDocumentPayload, SharedMemorySectionPayload


class CaseMemoryManager:
    """
    ケースメモリの読み書きを管理するクラス。
    read_shared_memoryはケースIDとワークスペースパスから共有メモリを読み込んでJSONで返す。
    write_shared_memoryはケースIDとワークスペースパスと内容から共有メモリに書き込む。
    """
    def __init__(self, config: AppConfig):
        self._memory_store = CaseMemoryStore(config)

    def build_default_read_shared_memory_tool(self):
        memory_store = self._memory_store

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
    
    

    def build_default_read_working_memory_tool(self, agent_name: str):
        memory_store = self._memory_store

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


    def build_default_write_shared_memory_tool(self):
        memory_store = self._memory_store

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


    def build_default_write_working_memory_tool(self, agent_name: str):
        memory_store = self._memory_store

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
