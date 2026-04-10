from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.case_id_resolver import CASE_ID_FILENAME


@dataclass(slots=True)
class CaseWorkspace:
    root: Path
    memory_dir: Path
    shared_context: Path
    shared_progress: Path
    shared_summary: Path
    agents_dir: Path
    artifacts_dir: Path
    evidence_dir: Path
    report_dir: Path


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
        return CaseWorkspace(
            root=root,
            memory_dir=memory_dir,
            shared_context=shared_dir / "context.md",
            shared_progress=shared_dir / "progress.md",
            shared_summary=shared_dir / "summary.md",
            agents_dir=agents_dir,
            artifacts_dir=artifacts_dir,
            evidence_dir=evidence_dir,
            report_dir=report_dir,
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
        self.write_case_id_marker(paths.root, case_id)

        self._write_if_missing(paths.shared_context, "# Shared Context\n\n")
        self._write_if_missing(paths.shared_progress, "# Shared Progress\n\n")
        self._write_if_missing(paths.shared_summary, "# Shared Summary\n\n")
        return paths

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