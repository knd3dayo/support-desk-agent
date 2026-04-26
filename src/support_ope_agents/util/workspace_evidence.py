from __future__ import annotations

from pathlib import Path
from typing import Iterable

from support_ope_agents.config.models import KnowledgeDocumentSource


_DEFAULT_EVIDENCE_DIRS = (".evidence", "evidence")
_ATTACHMENT_DIRS = (
    ".artifacts/intake/external_attachments",
    ".artifacts/intake/internal_attachments",
)
_PREFERRED_LOG_FILENAMES = ("application.log", "vdp.log")
_TEXT_LIKE_LOG_SUFFIXES = (".log", ".out", ".txt")
_ATTACHMENT_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def build_workspace_evidence_source(
    workspace_path: str | None,
    *,
    evidence_subdir: str = ".evidence",
    source_name: str = "workspace-evidence",
    description: str = "Current case workspace evidence files",
) -> KnowledgeDocumentSource | None:
    if not workspace_path:
        return None
    evidence_dir = Path(workspace_path).expanduser().resolve() / evidence_subdir
    if not evidence_dir.exists() or not evidence_dir.is_dir():
        return None
    return KnowledgeDocumentSource(
        name=source_name,
        description=description,
        path=evidence_dir,
    )


def _resolve_candidate_dirs(workspace_root: Path, relative_dirs: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for relative_dir in relative_dirs:
        candidate = workspace_root / relative_dir
        if candidate in seen:
            continue
        seen.add(candidate)
        resolved.append(candidate)
    return resolved


def find_evidence_log_file(workspace_path: str | None, *, include_attachment_dirs: bool = False) -> Path | None:
    if not workspace_path:
        return None
    workspace_root = Path(workspace_path).expanduser().resolve()
    relative_dirs = list(_DEFAULT_EVIDENCE_DIRS)
    if include_attachment_dirs:
        relative_dirs = [*_ATTACHMENT_DIRS, *relative_dirs]
    candidate_dirs = _resolve_candidate_dirs(workspace_root, relative_dirs)
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        for name in _PREFERRED_LOG_FILENAMES:
            candidate = directory / name
            if candidate.exists() and candidate.is_file():
                return candidate
        discovered_files = [path for path in sorted(directory.rglob("*")) if path.is_file()]
        for suffix in _TEXT_LIKE_LOG_SUFFIXES:
            for path in discovered_files:
                if path.suffix.lower() == suffix:
                    return path
    return None


def find_attachment_files(workspace_path: str | None) -> list[Path]:
    if not workspace_path:
        return []
    workspace_root = Path(workspace_path).expanduser().resolve()
    candidate_dirs = _resolve_candidate_dirs(workspace_root, [*_ATTACHMENT_DIRS, *_DEFAULT_EVIDENCE_DIRS])
    discovered: list[Path] = []
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in _ATTACHMENT_SUFFIXES and path not in discovered:
                discovered.append(path)
    return discovered