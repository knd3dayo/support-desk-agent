from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, model_validator


CaseStatus = Literal[
    "RECEIVED",
    "TRIAGED",
    "INVESTIGATING",
    "DRAFT_READY",
    "WAITING_APPROVAL",
    "WAITING_CUSTOMER_INPUT",
    "CLOSED",
]

WorkflowKind = Literal[
    "specification_inquiry",
    "incident_investigation",
    "ambiguous_case",
]

ExecutionMode = Literal["plan", "action"]


def _normalize_case_trace_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if normalized.startswith("SESSION-"):
        return f"TRACE-{normalized.removeprefix('SESSION-')}"
    if normalized.startswith("TRACE-"):
        return normalized
    return f"TRACE-{normalized}"


class CaseState(TypedDict, total=False):
    case_id: str
    case_title: str
    trace_id: str
    thread_id: str
    workflow_run_id: str
    workflow_kind: WorkflowKind
    execution_mode: ExecutionMode
    workspace_path: str
    intake_evidence_files: list[str]
    created_at: str
    status: CaseStatus
    raw_issue: str
    conversation_messages: list[dict[str, object]]
    masked_issue: str
    intake_category: WorkflowKind
    intake_urgency: str
    intake_investigation_focus: str
    intake_classification_reason: str
    intake_incident_timeframe: str
    log_extract_range_start: str
    log_extract_range_end: str
    intake_rework_required: bool
    intake_rework_reason: str
    intake_missing_fields: list[str]
    intake_followup_questions: dict[str, str]
    customer_followup_answers: dict[str, dict[str, str]]
    intake_ticket_context_summary: dict[str, str]
    intake_ticket_artifacts: dict[str, list[str]]
    external_ticket_id: str
    internal_ticket_id: str
    external_ticket_lookup_enabled: bool
    internal_ticket_lookup_enabled: bool
    plan_summary: str
    plan_steps: list[str]
    plan_evaluation_summary: str
    plan_evaluation_score: int
    investigation_summary: str
    investigation_followup_loops: int
    investigation_evaluation_summary: str
    investigation_evaluation_score: int
    supervisor_followup_notes: list[str]
    log_analysis_summary: str
    log_analysis_file: str
    knowledge_retrieval_summary: str
    knowledge_retrieval_results: list[dict[str, object]]
    knowledge_retrieval_adopted_sources: list[str]
    knowledge_retrieval_final_adopted_source: str
    escalation_required: bool
    escalation_reason: str
    escalation_summary: str
    escalation_missing_artifacts: list[str]
    escalation_draft: str
    compressed_summary: str
    draft_response: str
    review_focus: str
    draft_review_iterations: int
    draft_review_max_loops: int
    ticket_update_payload: str
    ticket_update_result: str
    approval_decision: str
    approval_history: list[dict[str, str]]
    agent_errors: list[dict[str, str]]
    context_usage: dict[str, int]
    current_agent: str
    next_action: str
    investigation_evidence_log_path: str
    investigation_attachment_paths: list[str]


class CaseStateModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str | None = None
    case_title: str | None = None
    trace_id: str | None = None
    thread_id: str | None = None
    workflow_run_id: str | None = None
    workflow_kind: WorkflowKind | None = None
    execution_mode: ExecutionMode | None = None
    workspace_path: str | None = None
    intake_evidence_files: list[str] | None = None
    created_at: str | None = None
    status: CaseStatus | None = None
    raw_issue: str | None = None
    conversation_messages: list[dict[str, object]] | None = None
    masked_issue: str | None = None
    intake_category: WorkflowKind | None = None
    intake_urgency: str | None = None
    intake_investigation_focus: str | None = None
    intake_classification_reason: str | None = None
    intake_incident_timeframe: str | None = None
    log_extract_range_start: str | None = None
    log_extract_range_end: str | None = None
    intake_rework_required: bool | None = None
    intake_rework_reason: str | None = None
    intake_missing_fields: list[str] | None = None
    intake_followup_questions: dict[str, str] | None = None
    customer_followup_answers: dict[str, dict[str, str]] | None = None
    intake_ticket_context_summary: dict[str, str] | None = None
    intake_ticket_artifacts: dict[str, list[str]] | None = None
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None
    external_ticket_lookup_enabled: bool | None = None
    internal_ticket_lookup_enabled: bool | None = None
    plan_summary: str | None = None
    plan_steps: list[str] | None = None
    plan_evaluation_summary: str | None = None
    plan_evaluation_score: int | None = None
    investigation_summary: str | None = None
    investigation_followup_loops: int | None = None
    investigation_evaluation_summary: str | None = None
    investigation_evaluation_score: int | None = None
    supervisor_followup_notes: list[str] | None = None
    log_analysis_summary: str | None = None
    log_analysis_file: str | None = None
    knowledge_retrieval_summary: str | None = None
    knowledge_retrieval_results: list[dict[str, object]] | None = None
    knowledge_retrieval_adopted_sources: list[str] | None = None
    knowledge_retrieval_final_adopted_source: str | None = None
    escalation_required: bool | None = None
    escalation_reason: str | None = None
    escalation_summary: str | None = None
    escalation_missing_artifacts: list[str] | None = None
    escalation_draft: str | None = None
    compressed_summary: str | None = None
    draft_response: str | None = None
    review_focus: str | None = None
    draft_review_iterations: int | None = None
    draft_review_max_loops: int | None = None
    ticket_update_payload: str | None = None
    ticket_update_result: str | None = None
    approval_decision: str | None = None
    approval_history: list[dict[str, str]] | None = None
    agent_errors: list[dict[str, str]] | None = None
    context_usage: dict[str, int] | None = None
    current_agent: str | None = None
    next_action: str | None = None
    investigation_evidence_log_path: str | None = None
    investigation_attachment_paths: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_trace_identifiers(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        session_id = str(normalized.pop("session_id", "") or "").strip()
        trace_id = _normalize_case_trace_id(
            str(normalized.get("trace_id") or normalized.get("thread_id") or normalized.get("workflow_run_id") or session_id)
        )
        if trace_id:
            normalized["trace_id"] = trace_id
            normalized["thread_id"] = trace_id
            normalized["workflow_run_id"] = trace_id
        return normalized

    def to_state_dict(self) -> CaseState:
        return cast(CaseState, self.model_dump(exclude_none=True))