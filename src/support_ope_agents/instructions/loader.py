from __future__ import annotations

from pathlib import Path

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore


class InstructionLoader:
    def __init__(self, config: AppConfig, memory_store: CaseMemoryStore):
        self._config = config
        self._memory_store = memory_store

    def load(self, case_id: str, role: str) -> str:
        del case_id
        parts: list[str] = []
        common_path = self._config.config_paths.instructions_path / "common.md"
        if common_path.exists():
            parts.append(common_path.read_text(encoding="utf-8").strip())

        role_path = self._config.config_paths.instructions_path / f"{role}.md"

        if role_path.exists():
            parts.append(role_path.read_text(encoding="utf-8").strip())

        return "\n\n".join(part for part in parts if part)

    def ensure_instruction_file(self, case_id: str, role: str) -> Path:
        del case_id
        path = self._config.config_paths.instructions_path / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {role}\n\n", encoding="utf-8")
        return path