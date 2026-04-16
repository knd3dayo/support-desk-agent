from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import FileInfo, GlobResult, GrepMatch, GrepResult, LsResult
import wcmatch.glob as wcglob


class FilteredFilesystemBackend(FilesystemBackend):
    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool | None = None,
        max_file_size_mb: int = 10,
        ignore_patterns: Sequence[str] | None = None,
    ) -> None:
        super().__init__(root_dir=root_dir, virtual_mode=virtual_mode, max_file_size_mb=max_file_size_mb)
        self._ignore_patterns = tuple(pattern.strip() for pattern in (ignore_patterns or ()) if pattern.strip())

    def _is_ignored_virtual_path(self, virtual_path: str) -> bool:
        relative_path = virtual_path.strip("/")
        if not relative_path:
            return False
        return any(
            wcglob.globmatch(relative_path, pattern, flags=wcglob.BRACE | wcglob.GLOBSTAR)
            for pattern in self._ignore_patterns
        )

    def _iter_searchable_files(self, search_path: Path):
        if search_path.is_file():
            virtual_path = self._to_virtual_path(search_path) if self.virtual_mode else str(search_path)
            if not self._is_ignored_virtual_path(virtual_path):
                yield search_path
            return

        for current_root, dirnames, filenames in search_path.walk(top_down=True):
            kept_dirnames: list[str] = []
            for dirname in dirnames:
                candidate = current_root / dirname
                virtual_path = self._to_virtual_path(candidate) if self.virtual_mode else str(candidate)
                if not self._is_ignored_virtual_path(virtual_path):
                    kept_dirnames.append(dirname)
            dirnames[:] = kept_dirnames

            for filename in filenames:
                candidate = current_root / filename
                virtual_path = self._to_virtual_path(candidate) if self.virtual_mode else str(candidate)
                if self._is_ignored_virtual_path(virtual_path):
                    continue
                yield candidate

    def ls(self, path: str) -> LsResult:
        result = super().ls(path)
        filtered_entries = [
            entry
            for entry in list(result.entries or [])
            if not self._is_ignored_virtual_path(str(entry.get("path") or ""))
        ]
        return LsResult(entries=filtered_entries)

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")

        search_path = self.cwd if path == "/" else self._resolve_path(path)
        if not search_path.exists():
            return GlobResult(matches=[])

        matches: list[FileInfo] = []
        base_dir = search_path if search_path.is_dir() else search_path.parent
        for candidate in self._iter_searchable_files(search_path):
            relative_path = candidate.relative_to(base_dir).as_posix()
            if not wcglob.globmatch(relative_path, pattern, flags=wcglob.BRACE | wcglob.GLOBSTAR):
                continue

            resolved_path = self._to_virtual_path(candidate) if self.virtual_mode else str(candidate)
            try:
                stat_result = candidate.stat()
                matches.append(
                    {
                        "path": resolved_path,
                        "is_dir": False,
                        "size": int(stat_result.st_size),
                        "modified_at": str(stat_result.st_mtime),
                    }
                )
            except OSError:
                matches.append({"path": resolved_path, "is_dir": False})

        matches.sort(key=lambda item: str(item.get("path") or ""))
        return GlobResult(matches=matches)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        try:
            search_path = self._resolve_path(path or ".")
        except ValueError:
            return GrepResult(matches=[])

        if not search_path.exists():
            return GrepResult(matches=[])

        regex = re.compile(re.escape(pattern))
        base_dir = search_path if search_path.is_dir() else search_path.parent
        matches: list[GrepMatch] = []
        for candidate in self._iter_searchable_files(search_path):
            relative_path = candidate.relative_to(base_dir).as_posix()
            if glob and not wcglob.globmatch(relative_path, glob, flags=wcglob.BRACE | wcglob.GLOBSTAR):
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line_text in enumerate(content.splitlines(), 1):
                if regex.search(line_text):
                    resolved_path = self._to_virtual_path(candidate) if self.virtual_mode else str(candidate)
                    matches.append({"path": resolved_path, "line": int(line_number), "text": line_text})
        return GrepResult(matches=matches)