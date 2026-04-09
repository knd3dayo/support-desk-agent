from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    COMPLIANCE_REVIEWER_SPECIALIST,
    DEFAULT_AGENT_ROLES,
    DRAFT_WRITER_SPECIALIST,
    INTAKE_AGENT,
    INVESTIGATION_AGENT,
    KNOWLEDGE_RETRIEVER_SPECIALIST,
    LOG_ANALYZER_SPECIALIST,
    RESOLUTION_AGENT,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
    canonical_role,
)
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
        normalized_role = canonical_role(role)
        base_tools: dict[str, list[ToolSpec]] = {
            SUPERVISOR_AGENT: [
                ToolSpec("inspect_workflow_state", "Inspect case workflow state", _not_implemented_tool("inspect_workflow_state")),
                ToolSpec("evaluate_agent_result", "Evaluate a child agent result", _not_implemented_tool("evaluate_agent_result")),
                ToolSpec("route_phase_agent", "Select next phase agent", _not_implemented_tool("route_phase_agent")),
            ],
            INTAKE_AGENT: [
                ToolSpec("pii_mask", "Mask PII from issue text or logs", _not_implemented_tool("pii_mask")),
                ToolSpec("classify_ticket", "Classify customer support ticket", _not_implemented_tool("classify_ticket")),
                ToolSpec("write_shared_memory", "Update shared memory files", _not_implemented_tool("write_shared_memory")),
            ],
            INVESTIGATION_AGENT: [
                ToolSpec("read_shared_memory", "Read shared case memory", _not_implemented_tool("read_shared_memory")),
                ToolSpec("scan_workspace_artifacts", "Scan workspace artifacts", _not_implemented_tool("scan_workspace_artifacts")),
                ToolSpec("spawn_log_analyzer_specialist", "Delegate to log analyzer specialist", _not_implemented_tool("spawn_log_analyzer_specialist")),
                ToolSpec("spawn_knowledge_retriever_specialist", "Delegate to knowledge retriever specialist", _not_implemented_tool("spawn_knowledge_retriever_specialist")),
            ],
            LOG_ANALYZER_SPECIALIST: [
                ToolSpec("read_log_file", "Read attached log file", _not_implemented_tool("read_log_file")),
                ToolSpec("run_python_analysis", "Run code-based log analysis", _not_implemented_tool("run_python_analysis")),
                ToolSpec("write_working_memory", "Write agent working memory", _not_implemented_tool("write_working_memory")),
            ],
            KNOWLEDGE_RETRIEVER_SPECIALIST: [
                ToolSpec("search_kb", "Search knowledge base", _not_implemented_tool("search_kb")),
                ToolSpec("search_ticket_history", "Search historical tickets", _not_implemented_tool("search_ticket_history")),
                ToolSpec("write_working_memory", "Write agent working memory", _not_implemented_tool("write_working_memory")),
            ],
            RESOLUTION_AGENT: [
                ToolSpec("read_shared_memory", "Read shared case memory", _not_implemented_tool("read_shared_memory")),
                ToolSpec("spawn_draft_writer_specialist", "Delegate draft creation", _not_implemented_tool("spawn_draft_writer_specialist")),
                ToolSpec("spawn_compliance_reviewer_specialist", "Delegate compliance review", _not_implemented_tool("spawn_compliance_reviewer_specialist")),
            ],
            DRAFT_WRITER_SPECIALIST: [
                ToolSpec("write_draft", "Write draft response", _not_implemented_tool("write_draft")),
            ],
            COMPLIANCE_REVIEWER_SPECIALIST: [
                ToolSpec("check_policy", "Check compliance policy", _not_implemented_tool("check_policy")),
                ToolSpec("request_revision", "Request draft revision", _not_implemented_tool("request_revision")),
            ],
            APPROVAL_AGENT: [
                ToolSpec("read_shared_memory", "Read shared case memory", _not_implemented_tool("read_shared_memory")),
                ToolSpec("record_approval_decision", "Record approval decision", _not_implemented_tool("record_approval_decision")),
                ToolSpec("write_override_instruction", "Write human override instruction", _not_implemented_tool("write_override_instruction")),
            ],
            TICKET_UPDATE_AGENT: [
                ToolSpec("zendesk_reply", "Reply to Zendesk ticket", _not_implemented_tool("zendesk_reply")),
                ToolSpec("redmine_update", "Update Redmine ticket", _not_implemented_tool("redmine_update")),
                ToolSpec("prepare_ticket_update", "Prepare external ticket update payload", _not_implemented_tool("prepare_ticket_update")),
            ],
        }
        return list(base_tools.get(normalized_role, []))

    def list_roles(self) -> Iterable[str]:
        return DEFAULT_AGENT_ROLES