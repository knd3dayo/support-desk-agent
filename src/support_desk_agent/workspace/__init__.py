from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "build_workspace_evidence_source",
    "find_attachment_files",
    "find_evidence_log_file",
    "CasePaths",
    "CaseWorkspace",
    "WorkspaceService",
    "CaseMemoryStore",
    "CaseMemoryManager",
]


def __getattr__(name: str) -> Any:
    module_map = {
        "build_workspace_evidence_source": ("support_desk_agent.workspace.evidence", "build_workspace_evidence_source"),
        "find_attachment_files": ("support_desk_agent.workspace.evidence", "find_attachment_files"),
        "find_evidence_log_file": ("support_desk_agent.workspace.evidence", "find_evidence_log_file"),
        "CasePaths": ("support_desk_agent.workspace.models", "CasePaths"),
        "CaseWorkspace": ("support_desk_agent.workspace.models", "CaseWorkspace"),
        "WorkspaceService": ("support_desk_agent.workspace.service", "WorkspaceService"),
        "CaseMemoryStore": ("support_desk_agent.workspace.store", "CaseMemoryStore"),
        "CaseMemoryManager": ("support_desk_agent.workspace.tools", "CaseMemoryManager"),
    }
    if name not in module_map:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = module_map[name]
    module = import_module(module_name)
    return getattr(module, attribute_name)