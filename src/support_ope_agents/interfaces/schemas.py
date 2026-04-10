from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    prompt: str
    workspace_path: str
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None


class ActionRequest(BaseModel):
    prompt: str
    workspace_path: str
    trace_id: str | None = None
    execution_plan: str | None = None
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None


class ResumeCustomerInputRequest(BaseModel):
    case_id: str
    trace_id: str
    workspace_path: str
    additional_input: str
    answer_key: str | None = None
    external_ticket_id: str | None = None
    internal_ticket_id: str | None = None


class DescribeAgentsRequest(BaseModel):
    prompt: str


class InitCaseRequest(BaseModel):
    prompt: str
    workspace_path: str


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


class InitCaseResponse(BaseModel):
    case_id: str
    case_path: str
