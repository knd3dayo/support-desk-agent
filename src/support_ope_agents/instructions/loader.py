from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Protocol

from support_ope_agents.config.models import AppConfig
from support_ope_agents.memory import CaseMemoryStore


class _ReadablePath(Protocol):
    def exists(self) -> bool: ...
    def read_text(self, encoding: str = "utf-8") -> str: ...


class InstructionLoader:
    def __init__(self, config: AppConfig, memory_store: CaseMemoryStore):
        self._config = config
        self._memory_store = memory_store
        self._default_instruction_root = files("support_ope_agents.instructions.defaults")

    @staticmethod
    def _read_if_exists(path: _ReadablePath) -> str:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def load(self, case_id: str, role: str) -> str:
        del case_id
        parts: list[str] = []

        default_common_path = self._default_instruction_root / "common.md"
        default_role_path = self._default_instruction_root / f"{role}.md"
        if default_common := self._read_if_exists(default_common_path):
            parts.append(default_common)
        if default_role := self._read_if_exists(default_role_path):
            parts.append(default_role)

        external_root = self._config.config_paths.instructions_path
        if external_root is not None:
            common_path = external_root / "common.md"
            role_path = external_root / f"{role}.md"
            if common_override := self._read_if_exists(common_path):
                parts.append(common_override)
            if role_override := self._read_if_exists(role_path):
                parts.append(role_override)

        return "\n\n".join(part for part in parts if part)

    def ensure_instruction_file(self, case_id: str, role: str) -> Path:
        del case_id
        external_root = self._config.config_paths.instructions_path
        if external_root is None:
            return Path(self._default_instruction_root.joinpath(f"{role}.md"))
        path = external_root / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {role}\n\n", encoding="utf-8")
        return path