from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LangChainMessageData(BaseModel):
    content: Any
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    id: str | None = None
    tool_call_id: str | None = None


class LangChainMessage(BaseModel):
    type: str
    data: LangChainMessageData


class PlanRequest(BaseModel):
    prompt: str
    workspace_path: str
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None


class ActionRequest(BaseModel):
    prompt: str
    case_id: str | None = None
    workspace_path: str
    trace_id: str | None = None
    execution_plan: str | None = None
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None
    chat_history: list["ChatMessage"] = Field(default_factory=list)
    conversation_messages: list[LangChainMessage] = Field(default_factory=list)


class ResumeCustomerInputRequest(BaseModel):
    case_id: str
    trace_id: str
    workspace_path: str
    additional_input: str
    answer_key: str | None = None
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None


class GenerateReportRequest(BaseModel):
    trace_id: str
    workspace_path: str
    checklist: list[str] = Field(default_factory=list)


class DescribeAgentsRequest(BaseModel):
    prompt: str


class InitCaseRequest(BaseModel):
    prompt: str
    workspace_path: str


class CreateCaseRequest(BaseModel):
    prompt: str
    case_id: str | None = None


class RuntimeEnvelope(BaseModel):
    case_id: str
    trace_id: str | None = None
    thread_id: str | None = None
    workflow_run_id: str | None = None
    workflow_kind: str | None = None
    workflow_label: str | None = None
    execution_mode: str | None = None
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None
    plan_summary: str | None = None
    plan_steps: list[str] = Field(default_factory=list)
    requires_approval: bool | None = None
    requires_customer_input: bool | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class GenerateReportResponse(BaseModel):
    case_id: str
    trace_id: str
    report_path: str
    sequence_diagram: str


class InitCaseResponse(BaseModel):
    case_id: str
    case_path: str
    case_title: str


class CaseSummary(BaseModel):
    case_id: str
    case_title: str
    workspace_path: str
    updated_at: str
    message_count: int = 0


class ChatMessage(BaseModel):
    role: str
    content: str
    trace_id: str | None = None
    event: str | None = None
    created_at: str | None = None


class ChatHistoryResponse(BaseModel):
    case_id: str
    workspace_path: str
    messages: list[ChatMessage] = Field(default_factory=list)
    conversation_messages: list[LangChainMessage] = Field(default_factory=list)


class WorkspaceEntry(BaseModel):
    name: str
    path: str
    kind: str
    size: int | None = None
    updated_at: str | None = None


class WorkspaceBrowseResponse(BaseModel):
    case_id: str
    workspace_path: str
    current_path: str
    entries: list[WorkspaceEntry] = Field(default_factory=list)


class WorkspaceFileResponse(BaseModel):
    case_id: str
    workspace_path: str
    path: str
    name: str
    mime_type: str | None = None
    preview_available: bool = True
    truncated: bool = False
    content: str | None = None


class WorkspaceUploadResponse(BaseModel):
    case_id: str
    workspace_path: str
    path: str
    size: int


class UiConfigResponse(BaseModel):
    app_name: str
    target_label: str | None = None
    target_description: str | None = None
    auth_required: bool = False

