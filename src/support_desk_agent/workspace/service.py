from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from support_desk_agent.agents.roles import DEFAULT_AGENT_ROLES
from support_desk_agent.config.models import AppConfig
from support_desk_agent.workspace.evidence import build_workspace_evidence_source, find_attachment_files, find_evidence_log_file
from support_desk_agent.workspace.store import CaseMemoryStore


TEXT_FILE_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".xml",
        ".csv",
        ".tsv",
        ".log",
        ".ini",
        ".cfg",
        ".conf",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".rb",
        ".go",
        ".rs",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".sh",
        ".bat",
    }
)


class WorkspaceService:
    def __init__(self, config: AppConfig):
        self._config = config
        self._store = CaseMemoryStore(config)

    @property
    def store(self) -> CaseMemoryStore:
        return self._store

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def initialize_case(self, case_id: str, workspace_path: str) -> Path:
        case_paths = self._store.initialize_case(case_id, workspace_path=workspace_path)
        for role in DEFAULT_AGENT_ROLES:
            self._store.ensure_agent_working_memory(case_id, role, workspace_path=workspace_path)
        return case_paths.root

    def list_workspace(self, *, case_id: str, workspace_path: str, relative_path: str = ".") -> dict[str, object]:
        entries = self._store.list_workspace_entries(case_id, workspace_path, relative_path)
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "current_path": "." if relative_path in {"", "."} else relative_path,
            "entries": entries,
        }

    def read_workspace_file(
        self,
        *,
        case_id: str,
        workspace_path: str,
        relative_path: str,
        max_chars: int | None = None,
        default_max_chars: int = 16000,
    ) -> dict[str, object]:
        target = self._store.resolve_workspace_path(case_id, workspace_path, relative_path)
        effective_max_chars = max_chars if max_chars is not None else default_max_chars
        guessed_mime, _ = mimetypes.guess_type(target.name)
        mime_type = guessed_mime or "application/octet-stream"
        is_text = target.suffix.lower() in TEXT_FILE_SUFFIXES or mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/xml",
            "application/yaml",
        }
        if not is_text:
            return {
                "case_id": case_id,
                "workspace_path": workspace_path,
                "path": relative_path,
                "name": target.name,
                "mime_type": mime_type,
                "preview_available": False,
                "truncated": False,
                "content": None,
            }

        content = self._store.read_workspace_text(
            case_id,
            workspace_path,
            relative_path,
            max_chars=effective_max_chars,
        )
        full_length = len(self._store.read_workspace_text(case_id, workspace_path, relative_path, max_chars=None))
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "path": relative_path,
            "name": target.name,
            "mime_type": mime_type,
            "preview_available": True,
            "truncated": full_length > effective_max_chars,
            "content": content,
        }

    def save_workspace_file(
        self,
        *,
        case_id: str,
        workspace_path: str,
        relative_dir: str,
        filename: str,
        content: bytes,
    ) -> dict[str, object]:
        safe_filename = Path(filename).name
        relative_path = str(Path(relative_dir or ".") / safe_filename)
        written = self._store.write_workspace_file(case_id, workspace_path, relative_path, content)
        return {
            "case_id": case_id,
            "workspace_path": workspace_path,
            "path": written.relative_to(CaseMemoryStore.resolve_root_path(workspace_path)).as_posix(),
            "size": written.stat().st_size,
        }

    def build_evidence_source(self, workspace_path: str | None, *, evidence_subdir: str = ".evidence"):
        return build_workspace_evidence_source(workspace_path, evidence_subdir=evidence_subdir)

    def find_evidence_log_file(
        self,
        workspace_path: str | None,
        *,
        include_attachment_dirs: bool = False,
        ignore_patterns: list[str] | tuple[str, ...] | None = None,
    ):
        return find_evidence_log_file(
            workspace_path,
            include_attachment_dirs=include_attachment_dirs,
            ignore_patterns=ignore_patterns,
        )

    def find_attachment_files(self, workspace_path: str | None, *, ignore_patterns: list[str] | tuple[str, ...] | None = None):
        return find_attachment_files(workspace_path, ignore_patterns=ignore_patterns)