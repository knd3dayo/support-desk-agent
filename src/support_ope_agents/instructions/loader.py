from __future__ import annotations

from pathlib import Path

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore


class InstructionLoader:
    def __init__(self, config: AppConfig, memory_store: CaseMemoryStore):
        self._config = config
        self._memory_store = memory_store

    def load(self, case_id: str, role: str) -> str:
        parts: list[str] = []
        common_path = self._config.paths.instructions_root / "common.md"
        role_path = self._config.paths.instructions_root / f"{role}.md"
        override_path = self._memory_store.resolve_case_paths(case_id).overrides_dir / f"{role}.md"

        for path in (common_path, role_path, override_path):
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())

        return "\n\n".join(part for part in parts if part)

    def ensure_override_file(self, case_id: str, role: str) -> Path:
        path = self._memory_store.resolve_case_paths(case_id).overrides_dir / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# Override: {role}\n\n", encoding="utf-8")
        return path