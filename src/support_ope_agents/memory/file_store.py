from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from support_ope_agents.agents.roles import candidate_role_names, canonical_role
from support_ope_agents.config.models import AppConfig


@dataclass(slots=True)
class CaseWorkspace:
    root: Path
    memory_dir: Path
    shared_context: Path
    shared_progress: Path
    shared_summary: Path
    agents_dir: Path
    overrides_dir: Path
    artifacts_dir: Path
    evidence_dir: Path
    workspace_manifest: Path


CasePaths = CaseWorkspace


class CaseMemoryStore:
    def __init__(self, config: AppConfig):
        self._config = config

    def resolve_case_paths(self, case_id: str) -> CasePaths:
        root = self._config.paths.workspace_root / case_id
        memory_dir = root / self._config.paths.shared_memory_subdir
        shared_dir = memory_dir / "shared"
        agents_dir = memory_dir / "agents"
        overrides_dir = root / self._config.paths.instruction_override_subdir
        artifacts_dir = root / self._config.paths.artifacts_subdir
        evidence_dir = root / self._config.paths.evidence_subdir
        workspace_manifest = root / self._config.paths.workspace_manifest_filename
        return CaseWorkspace(
            root=root,
            memory_dir=memory_dir,
            shared_context=shared_dir / "context.md",
            shared_progress=shared_dir / "progress.md",
            shared_summary=shared_dir / "summary.md",
            agents_dir=agents_dir,
            overrides_dir=overrides_dir,
            artifacts_dir=artifacts_dir,
            evidence_dir=evidence_dir,
            workspace_manifest=workspace_manifest,
        )

    def initialize_case(self, case_id: str, workspace_path: str | None = None) -> CasePaths:
        paths = self.resolve_case_paths(case_id)
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.memory_dir.mkdir(parents=True, exist_ok=True)
        paths.shared_context.parent.mkdir(parents=True, exist_ok=True)
        paths.agents_dir.mkdir(parents=True, exist_ok=True)
        paths.overrides_dir.mkdir(parents=True, exist_ok=True)
        paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
        paths.evidence_dir.mkdir(parents=True, exist_ok=True)

        self._write_if_missing(paths.shared_context, "# Shared Context\n\n")
        self._write_if_missing(paths.shared_progress, "# Shared Progress\n\n")
        self._write_if_missing(paths.shared_summary, "# Shared Summary\n\n")
        if workspace_path is not None:
            self.write_workspace_manifest(case_id, workspace_path)
        else:
            self._write_if_missing(paths.workspace_manifest, json.dumps({"workspace_path": "", "artifacts": []}, ensure_ascii=False, indent=2) + "\n")
        return paths

    def ensure_agent_working_memory(self, case_id: str, agent_name: str) -> Path:
        paths = self.resolve_case_paths(case_id)
        canonical_name = canonical_role(agent_name)
        working_dir = paths.agents_dir / canonical_name
        working_dir.mkdir(parents=True, exist_ok=True)
        working_file = working_dir / "working.md"
        self._write_if_missing(working_file, f"# Working Memory: {canonical_name}\n\n")
        return working_file

    def write_workspace_manifest(self, case_id: str, workspace_path: str) -> None:
        paths = self.resolve_case_paths(case_id)
        payload = {
            "workspace_path": workspace_path,
            "artifacts_dir": str(paths.artifacts_dir),
            "evidence_dir": str(paths.evidence_dir),
        }
        paths.workspace_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def read_workspace_manifest(self, case_id: str) -> dict[str, str]:
        paths = self.resolve_case_paths(case_id)
        if not paths.workspace_manifest.exists():
            return {}
        return json.loads(paths.workspace_manifest.read_text(encoding="utf-8"))

    def list_artifacts(self, case_id: str) -> list[Path]:
        paths = self.resolve_case_paths(case_id)
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

    def needs_compression(self, case_id: str, agent_name: str) -> bool:
        paths = self.resolve_case_paths(case_id)
        canonical_name = canonical_role(agent_name)
        working_file = paths.agents_dir / canonical_name / "working.md"
        total_length = len(self.read_text(paths.shared_context))
        total_length += len(self.read_text(paths.shared_progress))
        total_length += len(self.read_text(paths.shared_summary))
        total_length += len(self.read_text(working_file))
        return total_length >= self._config.workflow.compress_threshold_chars

    def resolve_existing_working_memory(self, case_id: str, agent_name: str) -> Path:
        paths = self.resolve_case_paths(case_id)
        for candidate_name in candidate_role_names(agent_name):
            candidate = paths.agents_dir / candidate_name / "working.md"
            if candidate.exists():
                return candidate
        return self.ensure_agent_working_memory(case_id, agent_name)

    def _write_if_missing(self, path: Path, content: str) -> None:
        if path.exists():
            return
        path.write_text(content, encoding="utf-8")