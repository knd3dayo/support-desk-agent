from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.case_id_resolver import CASE_ID_FILENAME


CASE_METADATA_FILENAME = ".support-ope-case.json"


@dataclass(slots=True)
class CaseWorkspace:
    root: Path
    case_metadata: Path
    memory_dir: Path
    shared_context: Path
    shared_progress: Path
    shared_summary: Path
    shared_history: Path
    agents_dir: Path
    artifacts_dir: Path
    evidence_dir: Path
    report_dir: Path
    traces_dir: Path


CasePaths = CaseWorkspace


class CaseMemoryStore:
    def __init__(self, config: AppConfig):
        self._config = config

    def read_case_id_marker(self, workspace_path: str | Path) -> str | None:
        marker = Path(workspace_path).expanduser().resolve() / CASE_ID_FILENAME
        if not marker.exists():
            return None
        value = marker.read_text(encoding="utf-8").strip()
        return value or None

    def write_case_id_marker(self, workspace_path: str | Path, case_id: str) -> Path:
        marker = Path(workspace_path).expanduser().resolve() / CASE_ID_FILENAME
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(case_id + "\n", encoding="utf-8")
        return marker

    @staticmethod
    def _resolve_root_path(workspace_path: str | Path) -> Path:
        return Path(workspace_path).expanduser().resolve()

    def resolve_case_paths(self, case_id: str, workspace_path: str) -> CasePaths:
        del case_id
        root = self._resolve_root_path(workspace_path)
        memory_dir = root / self._config.data_paths.shared_memory_subdir
        shared_dir = memory_dir / "shared"
        agents_dir = memory_dir / "agents"
        artifacts_dir = root / self._config.data_paths.artifacts_subdir
        evidence_dir = root / self._config.data_paths.evidence_subdir
        report_dir = root / self._config.data_paths.report_subdir
        traces_dir = root / self._config.data_paths.trace_subdir
        return CaseWorkspace(
            root=root,
            case_metadata=root / CASE_METADATA_FILENAME,
            memory_dir=memory_dir,
            shared_context=shared_dir / "context.md",
            shared_progress=shared_dir / "progress.md",
            shared_summary=shared_dir / "summary.md",
            shared_history=shared_dir / "chat_history.jsonl",
            agents_dir=agents_dir,
            artifacts_dir=artifacts_dir,
            evidence_dir=evidence_dir,
            report_dir=report_dir,
            traces_dir=traces_dir,
        )

    def initialize_case(self, case_id: str, workspace_path: str) -> CasePaths:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.memory_dir.mkdir(parents=True, exist_ok=True)
        paths.shared_context.parent.mkdir(parents=True, exist_ok=True)
        paths.agents_dir.mkdir(parents=True, exist_ok=True)
        paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
        paths.evidence_dir.mkdir(parents=True, exist_ok=True)
        paths.report_dir.mkdir(parents=True, exist_ok=True)
        paths.traces_dir.mkdir(parents=True, exist_ok=True)
        self.write_case_id_marker(paths.root, case_id)

        self._write_if_missing(paths.case_metadata, "{}\n")
        self._write_if_missing(paths.shared_context, "# Shared Context\n\n")
        self._write_if_missing(paths.shared_progress, "# Shared Progress\n\n")
        self._write_if_missing(paths.shared_summary, "# Shared Summary\n\n")
        self._write_if_missing(paths.shared_history, "")
        return paths

    def read_case_metadata(self, workspace_path: str | Path) -> dict[str, Any]:
        metadata_path = self._resolve_root_path(workspace_path) / CASE_METADATA_FILENAME
        if not metadata_path.exists():
            return {}
        try:
            parsed = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def update_case_metadata(self, workspace_path: str | Path, **updates: object) -> Path:
        metadata_path = self._resolve_root_path(workspace_path) / CASE_METADATA_FILENAME
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        current = self.read_case_metadata(workspace_path)
        for key, value in updates.items():
            if value is None:
                continue
            current[key] = value
        metadata_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return metadata_path

    def touch_case(self, workspace_path: str | Path, *, updated_at: str | None = None) -> Path:
        timestamp = updated_at or datetime.now(tz=UTC).isoformat()
        return self.update_case_metadata(workspace_path, updated_at=timestamp)

    def ensure_agent_working_memory(self, case_id: str, agent_name: str, workspace_path: str) -> Path:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        working_dir = paths.agents_dir / agent_name
        working_dir.mkdir(parents=True, exist_ok=True)
        working_file = working_dir / "working.md"
        self._write_if_missing(working_file, f"# Working Memory: {agent_name}\n\n")
        return working_file

    def list_artifacts(self, case_id: str, workspace_path: str) -> list[Path]:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        if not paths.artifacts_dir.exists():
            return []
        return sorted(path for path in paths.artifacts_dir.rglob("*") if path.is_file())

    def read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def append_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)

    def resolve_workspace_path(self, case_id: str, workspace_path: str, relative_path: str | Path = ".") -> Path:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        candidate = (paths.root / Path(relative_path)).resolve()
        if candidate != paths.root and not candidate.is_relative_to(paths.root):
            raise ValueError("path must stay within the case workspace")
        return candidate

    def list_workspace_entries(self, case_id: str, workspace_path: str, relative_path: str | Path = ".") -> list[dict[str, Any]]:
        target = self.resolve_workspace_path(case_id, workspace_path=workspace_path, relative_path=relative_path)
        if not target.exists():
            raise FileNotFoundError(target)
        if not target.is_dir():
            raise NotADirectoryError(target)

        entries: list[dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            relative_child = child.relative_to(self._resolve_root_path(workspace_path)).as_posix()
            entries.append(
                {
                    "name": child.name,
                    "path": relative_child,
                    "kind": "directory" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                    "updated_at": datetime.fromtimestamp(child.stat().st_mtime, tz=UTC).isoformat(),
                }
            )
        return entries

    def read_workspace_text(self, case_id: str, workspace_path: str, relative_path: str | Path, max_chars: int | None = None) -> str:
        target = self.resolve_workspace_path(case_id, workspace_path=workspace_path, relative_path=relative_path)
        if not target.exists():
            raise FileNotFoundError(target)
        if not target.is_file():
            raise IsADirectoryError(target)
        content = target.read_text(encoding="utf-8")
        if max_chars is None or max_chars < 0:
            return content
        return content[:max_chars]

    def write_workspace_file(self, case_id: str, workspace_path: str, relative_path: str | Path, content: bytes) -> Path:
        target = self.resolve_workspace_path(case_id, workspace_path=workspace_path, relative_path=relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        self.touch_case(workspace_path)
        return target

    def append_chat_history(self, case_id: str, workspace_path: str, message: dict[str, Any]) -> Path:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        paths.shared_history.parent.mkdir(parents=True, exist_ok=True)
        with paths.shared_history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        created_at = str(message.get("created_at") or "").strip() or None
        self.touch_case(workspace_path, updated_at=created_at)
        return paths.shared_history

    def read_chat_history(self, case_id: str, workspace_path: str) -> list[dict[str, Any]]:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        if not paths.shared_history.exists():
            return []
        history: list[dict[str, Any]] = []
        for line in paths.shared_history.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            history.append(json.loads(stripped))
        return history

    def needs_compression(self, case_id: str, agent_name: str, workspace_path: str) -> bool:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        working_file = paths.agents_dir / agent_name / "working.md"
        total_length = len(self.read_text(paths.shared_context))
        total_length += len(self.read_text(paths.shared_progress))
        total_length += len(self.read_text(paths.shared_summary))
        total_length += len(self.read_text(working_file))
        return total_length >= self._config.workflow.compress_threshold_chars

    def resolve_existing_working_memory(self, case_id: str, agent_name: str, workspace_path: str) -> Path:
        paths = self.resolve_case_paths(case_id, workspace_path=workspace_path)
        candidate = paths.agents_dir / agent_name / "working.md"
        if candidate.exists():
            return candidate
        return self.ensure_agent_working_memory(case_id, agent_name, workspace_path=workspace_path)

    def _write_if_missing(self, path: Path, content: str) -> None:
        if path.exists():
            return
        path.write_text(content, encoding="utf-8")