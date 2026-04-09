from __future__ import annotations

from typing import Literal, TypedDict


CaseStatus = Literal[
    "RECEIVED",
    "TRIAGED",
    "INVESTIGATING",
    "DRAFT_READY",
    "WAITING_APPROVAL",
    "CLOSED",
]


class CaseState(TypedDict, total=False):
    case_id: str
    trace_id: str
    thread_id: str
    workflow_run_id: str
    workspace_path: str
    created_at: str
    status: CaseStatus
    raw_issue: str
    masked_issue: str
    investigation_summary: str
    compressed_summary: str
    draft_response: str
    approval_decision: str
    approval_history: list[dict[str, str]]
    agent_errors: list[dict[str, str]]
    context_usage: dict[str, int]
    current_agent: str
    next_action: str