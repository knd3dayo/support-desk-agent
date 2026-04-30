from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CaseWorkspace:
    root: Path
    case_metadata: Path
    memory_dir: Path
    shared_context: Path
    shared_progress: Path
    shared_summary: Path
    shared_history: Path
    agents_dir: Path
    artifacts_dir: Path
    evidence_dir: Path
    report_dir: Path
    traces_dir: Path


CasePaths = CaseWorkspace