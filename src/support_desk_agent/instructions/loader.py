from __future__ import annotations

from importlib.resources import files, as_file
from pathlib import Path
from typing import Protocol

from support_desk_agent.config.models import AppConfig
from support_desk_agent.memory import CaseMemoryStore
from support_desk_agent.runtime.runtime_harness_manager import RuntimeHarnessManager


class _ReadablePath(Protocol):
    def exists(self) -> bool: ...
    def read_text(self, encoding: str = "utf-8") -> str: ...


class InstructionLoader:
    """
    指定されたroleやcase_idに応じて、指示文(instructions)をロードするローダークラス。
    デフォルトはパッケージ内リソース、外部パスが設定されていればそちらを優先。
    constraint_modeによってはinstructionsを抑制する。
    """
    def __init__(
        self,
        config: AppConfig,
        memory_store: CaseMemoryStore | None = None,
        runtime_harness_manager: RuntimeHarnessManager | None = None,
    ):
        """
        :param config: アプリ全体の設定
        :param memory_store: ケースメモリ管理（未使用でも型として必須）
        :param runtime_harness_manager: 実行時制約管理（省略可）
        """
        self._config = config
        self._memory_store = memory_store
        # デフォルトのinstructionsリソース(root)
        self._default_instruction_root = files("support_desk_agent.instructions.defaults")
        self._runtime_harness_manager = runtime_harness_manager

    @staticmethod
    def _read_if_exists(path: _ReadablePath) -> str:
        """
        指定パスが存在すればテキストを読み込んで返す。なければ空文字。
        """
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def load(self, case_id: str, role: str, *, constraint_mode: str | None = None) -> str:
        """
        指定role/case_idに対応するinstructionsをロードする。
        constraint_modeがruntime_only/bypassなら空文字を返す。
        優先順位: 外部パス > パッケージ内デフォルト
        """
        del case_id
        effective_constraint_mode = constraint_mode
        # 実行時制約が指定されていなければruntime_harness_managerから解決
        if effective_constraint_mode is None and self._runtime_harness_manager is not None:
            effective_constraint_mode = self._runtime_harness_manager.resolve(role)
        if effective_constraint_mode is None:
            effective_constraint_mode = "default"
        if effective_constraint_mode in {"runtime_only", "bypass"}:
            # runtime_only/bypass時はinstructionsを抑制
            return ""

        parts: list[str] = []

        # デフォルト（パッケージ内リソース）をas_fileでPath化して読む
        default_common_path = self._default_instruction_root / "common.md"
        default_role_path = self._default_instruction_root / f"{role}.md"
        with as_file(default_common_path) as common_file, as_file(default_role_path) as role_file:
            if default_common := self._read_if_exists(common_file):
                parts.append(default_common)
            if default_role := self._read_if_exists(role_file):
                parts.append(default_role)

        # 外部パスが指定されていればそちらを優先的に読む
        external_root = self._config.config_paths.instructions_path
        if external_root is not None:
            common_path = external_root / "common.md"
            role_path = external_root / f"{role}.md"
            if common_override := self._read_if_exists(common_path):
                parts.append(common_override)
            if role_override := self._read_if_exists(role_path):
                parts.append(role_override)

        # 空でなければ結合して返す
        return "\n\n".join(part for part in parts if part)

    def ensure_instruction_file(self, case_id: str, role: str) -> Path:
        """
        指定roleのinstructionsファイルが外部パスに存在しなければ作成し、そのPathを返す。
        外部パス未指定時はパッケージ内リソースのPathを返す（readonly）。
        """
        del case_id
        external_root = self._config.config_paths.instructions_path
        if external_root is None:
            # パッケージ内リソースのPath（編集不可）
            default_role_path = self._default_instruction_root / f"{role}.md"
            with as_file(default_role_path) as role_file:
                return Path(role_file)
        path = external_root / f"{role}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {role}\n\n", encoding="utf-8")
        return path