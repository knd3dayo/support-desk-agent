from __future__ import annotations

from pathlib import Path

from support_ope_agents.agents.roles import candidate_role_names, canonical_role
from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore


class InstructionLoader:
    def __init__(self, config: AppConfig, memory_store: CaseMemoryStore):
        self._config = config
        self._memory_store = memory_store

    def load(self, case_id: str, role: str) -> str:
        parts: list[str] = []
        common_path = self._config.paths.instructions_root / "common.md"
        if common_path.exists():
            parts.append(common_path.read_text(encoding="utf-8").strip())

        case_paths = self._memory_store.resolve_case_paths(case_id)
        role_path = self._first_existing_path(
            self._config.paths.instructions_root / f"{candidate_role}.md"
            for candidate_role in candidate_role_names(role)
        )
        override_path = self._first_existing_path(
            case_paths.overrides_dir / f"{candidate_role}.md"
            for candidate_role in candidate_role_names(role)
        )

        for path in (role_path, override_path):
            if path is not None and path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())

        return "\n\n".join(part for part in parts if part)

    def ensure_override_file(self, case_id: str, role: str) -> Path:
        canonical = canonical_role(role)
        path = self._memory_store.resolve_case_paths(case_id).overrides_dir / f"{canonical}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# Override: {canonical}\n\n", encoding="utf-8")
        return path

    @staticmethod
    def _first_existing_path(paths: list[Path] | tuple[Path, ...] | object) -> Path | None:
        for path in paths:
            if isinstance(path, Path) and path.exists():
                return path
        return None