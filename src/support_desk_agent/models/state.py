from __future__ import annotations

from typing import Any, Literal, Mapping

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


class CaseState(BaseModel):
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

    def to_state_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)

    def __len__(self) -> int:
        return len(self.to_state_dict())

    def __getitem__(self, key: str) -> Any:
        if key in self.model_fields:
            value = getattr(self, key)
            if value is None:
                raise KeyError(key)
            return value
        extra = self.model_extra or {}
        if key not in extra:
            raise KeyError(key)
        return extra[key]

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def setdefault(self, key: str, default: Any) -> Any:
        value = self.get(key)
        if value is None:
            self[key] = default
            return default
        return value

    def update(self, other: dict[str, Any] | "CaseState" | None = None, **kwargs: Any) -> None:
        merged = as_state_dict(other or {})
        merged.update(kwargs)
        for key, value in merged.items():
            self[key] = value

    def items(self):
        return self.to_state_dict().items()

    def keys(self):
        return self.to_state_dict().keys()

    def values(self):
        return self.to_state_dict().values()


def as_state_dict(state: CaseState | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(state, CaseState):
        return state.to_state_dict()
    return dict(state)
