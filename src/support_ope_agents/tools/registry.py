from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from support_ope_agents.config.models import AppConfig


ToolCallable = Callable[..., str]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolCallable


def _not_implemented_tool(name: str) -> ToolCallable:
    def _handler(*_: object, **__: object) -> str:
        return f"Tool '{name}' is not implemented yet."

    return _handler


class ToolRegistry:
    def __init__(self, config: AppConfig):
        self._config = config

    def get_tools(self, role: str) -> list[ToolSpec]:
        base_tools: dict[str, list[ToolSpec]] = {
            "intake_supervisor": [
                ToolSpec("pii_mask", "Mask PII from issue text or logs", _not_implemented_tool("pii_mask")),
                ToolSpec("classify_ticket", "Classify customer support ticket", _not_implemented_tool("classify_ticket")),
                ToolSpec("write_shared_memory", "Update shared memory files", _not_implemented_tool("write_shared_memory")),
            ],
            "investigation_supervisor": [
                ToolSpec("read_shared_memory", "Read shared case memory", _not_implemented_tool("read_shared_memory")),
                ToolSpec("spawn_log_analyzer", "Delegate to log analyzer", _not_implemented_tool("spawn_log_analyzer")),
                ToolSpec("spawn_knowledge_retriever", "Delegate to knowledge retriever", _not_implemented_tool("spawn_knowledge_retriever")),
            ],
            "log_analyzer": [
                ToolSpec("read_log_file", "Read attached log file", _not_implemented_tool("read_log_file")),
                ToolSpec("run_python_analysis", "Run code-based log analysis", _not_implemented_tool("run_python_analysis")),
                ToolSpec("write_working_memory", "Write agent working memory", _not_implemented_tool("write_working_memory")),
            ],
            "knowledge_retriever": [
                ToolSpec("search_kb", "Search knowledge base", _not_implemented_tool("search_kb")),
                ToolSpec("search_ticket_history", "Search historical tickets", _not_implemented_tool("search_ticket_history")),
                ToolSpec("write_working_memory", "Write agent working memory", _not_implemented_tool("write_working_memory")),
            ],
            "resolution_supervisor": [
                ToolSpec("read_shared_memory", "Read shared case memory", _not_implemented_tool("read_shared_memory")),
                ToolSpec("spawn_draft_writer", "Delegate draft creation", _not_implemented_tool("spawn_draft_writer")),
                ToolSpec("spawn_compliance_reviewer", "Delegate compliance review", _not_implemented_tool("spawn_compliance_reviewer")),
            ],
            "draft_writer": [
                ToolSpec("write_draft", "Write draft response", _not_implemented_tool("write_draft")),
            ],
            "compliance_reviewer": [
                ToolSpec("check_policy", "Check compliance policy", _not_implemented_tool("check_policy")),
                ToolSpec("request_revision", "Request draft revision", _not_implemented_tool("request_revision")),
            ],
            "ticket_update": [
                ToolSpec("zendesk_reply", "Reply to Zendesk ticket", _not_implemented_tool("zendesk_reply")),
                ToolSpec("redmine_update", "Update Redmine ticket", _not_implemented_tool("redmine_update")),
            ],
        }
        return list(base_tools.get(role, []))

    def list_roles(self) -> Iterable[str]:
        return (
            "intake_supervisor",
            "investigation_supervisor",
            "log_analyzer",
            "knowledge_retriever",
            "resolution_supervisor",
            "draft_writer",
            "compliance_reviewer",
            "ticket_update",
        )