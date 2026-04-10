from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Callable, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT, SUPERVISOR_AGENT


@dataclass(slots=True)
class ComplianceReviewerPhaseExecutor:
    check_policy_tool: Callable[..., Any]
    request_revision_tool: Callable[..., Any]

    def _invoke_tool(self, tool: Callable[..., Any], *args: object, **kwargs: object) -> str:
        try:
            result = tool(*args, **kwargs)
        except TypeError:
            result = tool(*args)
        if inspect.isawaitable(result):
            try:
                resolved = asyncio.run(cast(Coroutine[Any, Any, Any], result))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    resolved = loop.run_until_complete(result)
                finally:
                    loop.close()
            return str(resolved)
        return str(result)

    def execute(self, state: dict[str, object]) -> dict[str, object]:
        draft_response = str(state.get("draft_response") or "")
        review_focus = str(state.get("review_focus") or "")
        raw_policy_result = self._invoke_tool(
            self.check_policy_tool,
            draft_response=draft_response,
            review_focus=review_focus,
        )
        try:
            parsed = json.loads(raw_policy_result)
        except json.JSONDecodeError:
            parsed = {"status": "revision_required", "message": raw_policy_result, "issues": [raw_policy_result]}

        issues = [str(item).strip() for item in list(parsed.get("issues") or []) if str(item).strip()]
        review_summary = str(parsed.get("message") or "")
        raw_revision_result = self._invoke_tool(
            self.request_revision_tool,
            issues=issues,
            review_summary=review_summary,
            draft_response=draft_response,
        )
        try:
            revision = json.loads(raw_revision_result)
        except json.JSONDecodeError:
            revision = {"status": "revision_required" if issues else "no_revision", "revision_points": [raw_revision_result]}

        notice_check = parsed.get("notice_check") if isinstance(parsed, dict) else {}
        review_passed = str(parsed.get("status") or "") == "passed"
        return {
            "compliance_review_summary": review_summary or ("レビューを通過しました。" if review_passed else "レビューで修正が必要です。"),
            "compliance_review_results": list(parsed.get("results") or []) if isinstance(parsed, dict) else [],
            "compliance_review_adopted_sources": list(parsed.get("adopted_sources") or []) if isinstance(parsed, dict) else [],
            "compliance_review_issues": issues,
            "compliance_notice_present": bool((notice_check or {}).get("present")),
            "compliance_notice_matched_phrase": str((notice_check or {}).get("matched_phrase") or ""),
            "compliance_revision_request": "\n".join(list(revision.get("revision_points") or [])),
            "compliance_review_passed": review_passed,
        }


def build_compliance_reviewer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        COMPLIANCE_REVIEWER_AGENT,
        "Review draft against policy",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )