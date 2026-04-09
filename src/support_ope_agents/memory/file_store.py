from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from support_ope_agents.config.models import AppConfig


@dataclass(slots=True)
class CasePaths:
    root: Path
    memory_dir: Path
    shared_context: Path
    shared_progress: Path
    shared_summary: Path
    agents_dir: Path
    overrides_dir: Path


class CaseMemoryStore:
    def __init__(self, config: AppConfig):
        self._config = config

    def resolve_case_paths(self, case_id: str) -> CasePaths:
        root = self._config.paths.workspace_root / case_id
        memory_dir = root / self._config.paths.shared_memory_subdir
        shared_dir = memory_dir / "shared"
        agents_dir = memory_dir / "agents"
        overrides_dir = root / self._config.paths.instruction_override_subdir
        return CasePaths(
            root=root,
            memory_dir=memory_dir,
            shared_context=shared_dir / "context.md",
            shared_progress=shared_dir / "progress.md",
            shared_summary=shared_dir / "summary.md",
            agents_dir=agents_dir,
            overrides_dir=overrides_dir,
        )

    def initialize_case(self, case_id: str) -> CasePaths:
        paths = self.resolve_case_paths(case_id)
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.memory_dir.mkdir(parents=True, exist_ok=True)
        paths.shared_context.parent.mkdir(parents=True, exist_ok=True)
        paths.agents_dir.mkdir(parents=True, exist_ok=True)
        paths.overrides_dir.mkdir(parents=True, exist_ok=True)

        self._write_if_missing(paths.shared_context, "# Shared Context\n\n")
        self._write_if_missing(paths.shared_progress, "# Shared Progress\n\n")
        self._write_if_missing(paths.shared_summary, "# Shared Summary\n\n")
        return paths

    def ensure_agent_working_memory(self, case_id: str, agent_name: str) -> Path:
        paths = self.resolve_case_paths(case_id)
        working_dir = paths.agents_dir / agent_name
        working_dir.mkdir(parents=True, exist_ok=True)
        working_file = working_dir / "working.md"
        self._write_if_missing(working_file, f"# Working Memory: {agent_name}\n\n")
        return working_file

    def read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def append_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)

    def needs_compression(self, case_id: str, agent_name: str) -> bool:
        paths = self.resolve_case_paths(case_id)
        working_file = paths.agents_dir / agent_name / "working.md"
        total_length = len(self.read_text(paths.shared_context))
        total_length += len(self.read_text(paths.shared_progress))
        total_length += len(self.read_text(paths.shared_summary))
        total_length += len(self.read_text(working_file))
        return total_length >= self._config.workflow.compress_threshold_chars

    def _write_if_missing(self, path: Path, content: str) -> None:
        if path.exists():
            return
        path.write_text(content, encoding="utf-8")