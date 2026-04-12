from __future__ import annotations

from typing import Literal, TypedDict


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
    masked_issue: str
    intake_category: WorkflowKind
    intake_urgency: str
    intake_investigation_focus: str
    intake_classification_reason: str
    intake_incident_timeframe: str
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
    investigation_summary: str
    investigation_followup_loops: int
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
    compliance_review_summary: str
    compliance_review_results: list[dict[str, object]]
    compliance_review_adopted_sources: list[str]
    compliance_review_issues: list[str]
    compliance_notice_present: bool
    compliance_notice_matched_phrase: str
    compliance_revision_request: str
    compliance_review_passed: bool
    compliance_review_history: list[dict[str, object]]
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