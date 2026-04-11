from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(frozen=True, slots=True)
class IntakeValidationResult:
    category: str
    urgency: str
    incident_timeframe: str
    missing_fields: list[str]
    rework_reason: str


def resolve_intake_category(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
    state_category = str(state.get("intake_category") or "").strip()
    if state_category:
        return state_category

    combined = "\n".join(memory_snapshot.values())
    match = re.search(r"(?:Category|Intake category):\s*([^\n]+)", combined)
    if match:
        return match.group(1).strip()
    return "ambiguous_case"


def resolve_intake_urgency(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
    state_urgency = str(state.get("intake_urgency") or "").strip()
    if state_urgency:
        return state_urgency

    combined = "\n".join(memory_snapshot.values())
    match = re.search(r"(?:Urgency|Intake urgency):\s*([^\n]+)", combined)
    if match:
        return match.group(1).strip()
    return "medium"


def resolve_incident_timeframe(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
    timeframe = str(state.get("intake_incident_timeframe") or "").strip()
    if timeframe:
        return timeframe

    combined = "\n".join(memory_snapshot.values())
    match = re.search(r"Incident timeframe:\s*([^\n]+)", combined)
    if match:
        return match.group(1).strip()
    return ""


def resolve_effective_workflow_kind(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
    workflow_kind = str(state.get("workflow_kind") or "").strip()
    intake_category = resolve_intake_category(state, memory_snapshot)
    valid_values = {"specification_inquiry", "incident_investigation", "ambiguous_case"}

    if workflow_kind not in valid_values:
        return intake_category if intake_category in valid_values else "ambiguous_case"

    if workflow_kind == "ambiguous_case" and intake_category in {"specification_inquiry", "incident_investigation"}:
        return intake_category

    return workflow_kind


def validate_intake(state: "CaseState", memory_snapshot: dict[str, str]) -> IntakeValidationResult:
    missing_fields: list[str] = []
    category = resolve_intake_category(state, memory_snapshot)
    urgency = resolve_intake_urgency(state, memory_snapshot)
    incident_timeframe = resolve_incident_timeframe(state, memory_snapshot)

    if not category:
        missing_fields.append("intake_category")
    if not urgency:
        missing_fields.append("intake_urgency")
    if category == "incident_investigation" and not incident_timeframe:
        missing_fields.append("intake_incident_timeframe")

    rework_reason = ""
    if missing_fields:
        reasons = {
            "intake_category": "問い合わせ分類が未確定",
            "intake_urgency": "緊急度が未設定",
            "intake_incident_timeframe": "障害発生時間帯が未確認",
        }
        rework_reason = "、".join(reasons[field_name] for field_name in missing_fields)

    return IntakeValidationResult(
        category=category,
        urgency=urgency,
        incident_timeframe=incident_timeframe,
        missing_fields=missing_fields,
        rework_reason=rework_reason,
    )