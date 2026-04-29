from __future__ import annotations

import json
from typing import Any

from support_desk_agent.config.models import AppConfig


def build_default_prepare_ticket_update_tool(_config: AppConfig):
    async def prepare_ticket_update(
        draft_response: str = "",
        escalation_draft: str = "",
        external_ticket_id: str = "",
        internal_ticket_id: str = "",
        intake_ticket_context_summary: dict[str, str] | None = None,
        ticket_followup_questions: dict[str, str] | None = None,
    ) -> str:
        ticket_summaries = dict(intake_ticket_context_summary or {})
        followup_questions = {
            str(key): str(value).strip()
            for key, value in (ticket_followup_questions or {}).items()
            if str(value).strip()
        }

        lines: list[str] = []
        normalized_escalation_draft = str(escalation_draft).strip()
        normalized_draft_response = str(draft_response).strip()
        if normalized_escalation_draft:
            lines.extend(["Back support inquiry prepared:", normalized_escalation_draft])
        elif normalized_draft_response:
            lines.extend(["Customer reply prepared:", normalized_draft_response])
        else:
            lines.append("Zendesk / Redmine に反映する更新内容を準備しました。")

        ticket_ids = {
            "external": str(external_ticket_id).strip(),
            "internal": str(internal_ticket_id).strip(),
        }
        for ticket_kind, ticket_id in ticket_ids.items():
            summary = str(ticket_summaries.get(f"{ticket_kind}_ticket") or "").strip()
            followup_question = followup_questions.get(f"{ticket_kind}_ticket_confirmation", "")
            if not ticket_id and not summary and not followup_question:
                continue
            lines.extend(["", f"{ticket_kind.title()} ticket id: {ticket_id or 'n/a'}"])
            if summary:
                lines.extend([f"{ticket_kind.title()} ticket summary:", summary])
            if followup_question:
                lines.extend([f"{ticket_kind.title()} ticket follow-up required:", followup_question])

        return json.dumps({"payload": "\n".join(lines).strip()}, ensure_ascii=False)

    return prepare_ticket_update