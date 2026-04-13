from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload


@dataclass(slots=True)
class ComplianceReviewerPhaseExecutor:
    check_policy_tool: Callable[..., Any]
    request_revision_tool: Callable[..., Any]
    write_working_memory_tool: Callable[..., Any] | None = None
    constraint_mode: str = "default"

    def _runtime_constraints_enabled(self) -> bool:
        # Runtime constraint: review tools run only when runtime constraints are enabled.
        return RuntimeHarnessManager.runtime_constraints_enabled_for_mode(self.constraint_mode)

    def _invoke_tool(self, tool: Callable[..., Any], *args: object, **kwargs: object) -> str:
        try:
            result = tool(*args, **kwargs)
        except TypeError:
            result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(cast(Any, result))
            return str(resolved)
        return str(result)

    @staticmethod
    def _build_working_memory_sections(results: list[dict[str, object]]) -> list[dict[str, object]]:
        sections: list[dict[str, object]] = []
        for item in results:
            source_name = str(item.get("source_name") or "unknown").strip() or "unknown"
            sections.append(
                {
                    "title": f"Result: {source_name}",
                    "bullets": [f"Raw result: {json.dumps(item, ensure_ascii=False)}"],
                }
            )
        return sections

    def execute(self, state: dict[str, object]) -> dict[str, object]:
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        draft_response = str(state.get("draft_response") or "")
        review_focus = str(state.get("review_focus") or "")
        if not self._runtime_constraints_enabled():
            # Runtime constraint: bypass and instruction_only skip compliance review entirely.
            return {
                "compliance_review_summary": "constraint_mode により ComplianceReviewerAgent の runtime review を省略しました。",
                "compliance_review_results": [],
                "compliance_review_adopted_sources": [],
                "compliance_review_issues": [],
                "compliance_notice_present": False,
                "compliance_notice_matched_phrase": "",
                "compliance_revision_request": "",
                "compliance_review_passed": True,
            }

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
        review_results = list(parsed.get("results") or []) if isinstance(parsed, dict) else []
        adopted_sources = list(parsed.get("adopted_sources") or []) if isinstance(parsed, dict) else []

        if self.write_working_memory_tool is not None and case_id and workspace_path:
            payload: SharedMemoryDocumentPayload = {
                "title": "Compliance Review Result",
                "heading_level": 2,
                "bullets": [
                    f"Review focus: {review_focus or 'n/a'}",
                    f"Review passed: {'yes' if review_passed else 'no'}",
                    f"Summary: {review_summary or ('レビューを通過しました。' if review_passed else 'レビューで修正が必要です。')}",
                    f"Adopted sources: {', '.join(str(item) for item in adopted_sources) if adopted_sources else 'none'}",
                    f"Issues: {' | '.join(issues) if issues else 'none'}",
                ],
                "sections": self._build_working_memory_sections(
                    [item for item in review_results if isinstance(item, dict)]
                ),
            }
            self._invoke_tool(self.write_working_memory_tool, case_id, workspace_path, payload, "append")

        return {
            "compliance_review_summary": review_summary or ("レビューを通過しました。" if review_passed else "レビューで修正が必要です。"),
            "compliance_review_results": review_results,
            "compliance_review_adopted_sources": adopted_sources,
            "compliance_review_issues": issues,
            "compliance_notice_present": bool((notice_check or {}).get("present")),
            "compliance_notice_matched_phrase": str((notice_check or {}).get("matched_phrase") or ""),
            "compliance_revision_request": "\n".join(list(revision.get("revision_points") or [])),
            "compliance_review_passed": review_passed,
        }

    @staticmethod
    def build_compliance_reviewer_agent_definition() -> AgentDefinition:
        return AgentDefinition(
            COMPLIANCE_REVIEWER_AGENT,
            "Review draft against policy",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )
