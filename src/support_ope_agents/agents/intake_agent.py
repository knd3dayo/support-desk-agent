from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class IntakePhaseExecutor:
    pii_mask_tool: Callable[..., Any]
    classify_ticket_tool: Callable[..., Any]
    write_shared_memory_tool: Callable[..., Any]

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
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

    @staticmethod
    def _parse_classification(raw_result: str) -> dict[str, str]:
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return {"category": "ambiguous_case", "urgency": "medium", "investigation_focus": raw_result.strip()}

        if not isinstance(parsed, dict):
            return {"category": "ambiguous_case", "urgency": "medium", "investigation_focus": str(parsed)}

        return {
            "category": str(parsed.get("category") or "ambiguous_case"),
            "urgency": str(parsed.get("urgency") or "medium"),
            "investigation_focus": str(parsed.get("investigation_focus") or "問い合わせ内容の事実関係を確認する"),
            "reason": str(parsed.get("reason") or ""),
        }

    @staticmethod
    def _extract_incident_timeframe(text: str) -> str:
        patterns = (
            r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?\b",
            r"\b\d{4}/\d{1,2}/\d{1,2}(?:\s+\d{1,2}:\d{2})?\b",
            r"\b\d{1,2}:\d{2}\b",
            r"(今日|昨日|一昨日|今朝|昨夜|本日|昨日の夜|本日午前|本日午後|午前|午後|深夜|夕方|朝方)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip()
        return ""

    @staticmethod
    def _build_followup_questions(missing_fields: list[str]) -> dict[str, str]:
        questions: dict[str, str] = {}
        for field_name in missing_fields:
            if field_name == "intake_category":
                questions[field_name] = "この問い合わせは仕様確認、障害調査、どちらの可能性が高いか分かる追加状況を教えてください。"
            elif field_name == "intake_urgency":
                questions[field_name] = "影響範囲と緊急度を教えてください。業務停止か、一部影響か、回避策の有無もあると助かります。"
            elif field_name == "intake_incident_timeframe":
                questions[field_name] = "障害が最初に発生した日時、または少なくとも発生した時間帯を教えてください。"
        return questions

    def execute(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "TRIAGED"
        update["current_agent"] = INTAKE_AGENT

        raw_issue = str(update.get("raw_issue") or "").strip()
        masked_issue = raw_issue
        classification = {
            "category": "ambiguous_case",
            "urgency": "medium",
            "investigation_focus": "問い合わせ内容の事実関係を確認する",
            "reason": "",
        }
        incident_timeframe = ""
        if raw_issue:
            masked_issue = self._invoke_tool(self.pii_mask_tool, raw_issue, "Mask API keys, tokens, and secrets for intake processing.")
            classification = self._parse_classification(
                self._invoke_tool(
                    self.classify_ticket_tool,
                    masked_issue,
                    "Classify the intake issue for customer support workflow routing and investigation planning.",
                )
            )
            update["masked_issue"] = masked_issue
            update["intake_category"] = classification["category"]
            update["intake_urgency"] = classification["urgency"]
            update["intake_investigation_focus"] = classification["investigation_focus"]
            update["intake_classification_reason"] = classification.get("reason", "")
            incident_timeframe = self._extract_incident_timeframe(masked_issue)
            update["intake_incident_timeframe"] = incident_timeframe

        missing_fields = cast(list[str], update.get("intake_missing_fields") or [])
        followup_questions: dict[str, str] = {}
        if update.get("intake_rework_required") and missing_fields:
            followup_questions = self._build_followup_questions(missing_fields)
            update["status"] = "WAITING_CUSTOMER_INPUT"
            update["intake_followup_questions"] = followup_questions
            update.setdefault("customer_followup_answers", {})
            update["next_action"] = "不足情報をユーザーへ確認し、追加入力後に Intake を再実行する"
        else:
            update["intake_followup_questions"] = {}

        workspace_path = str(update.get("workspace_path") or "").strip()
        case_id = str(update.get("case_id") or "").strip()
        if workspace_path and case_id:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Shared Context",
                "heading_level": 1,
                "bullets": [f"Case ID: {case_id}"],
            }
            trace_id = str(update.get("trace_id") or "").strip()
            if trace_id:
                context_payload["bullets"].append(f"Trace ID: {trace_id}")
            if raw_issue:
                context_payload["sections"] = [
                    {
                        "title": "Intake Summary",
                        "bullets": [
                            f"Raw issue: {raw_issue}",
                            f"Masked issue: {masked_issue}",
                            f"Category: {classification['category']}",
                            f"Urgency: {classification['urgency']}",
                            f"Investigation focus: {classification['investigation_focus']}",
                        ],
                    }
                ]
                if incident_timeframe:
                    context_payload["sections"][0]["bullets"].append(f"Incident timeframe: {incident_timeframe}")
                if classification.get("reason"):
                    context_payload["sections"][0]["bullets"].append(f"Reason: {classification['reason']}")
                structured_answers = cast(dict[str, dict[str, str]], update.get("customer_followup_answers") or {})
                if structured_answers:
                    answer_bullets: list[str] = []
                    for field_name, item in structured_answers.items():
                        question = str(item.get("question") or "").strip()
                        answer = str(item.get("answer") or "").strip()
                        if question and answer:
                            answer_bullets.append(f"{field_name}: Q: {question} / A: {answer}")
                        elif answer:
                            answer_bullets.append(f"{field_name}: A: {answer}")
                    if answer_bullets:
                        context_payload["sections"].append(
                            {
                                "title": "Customer Follow-up Answers",
                                "bullets": answer_bullets,
                            }
                        )
                if followup_questions:
                    context_payload["sections"].append(
                        {
                            "title": "Intake Follow-up Required",
                            "bullets": [f"{field_name}: {question}" for field_name, question in followup_questions.items()],
                        }
                    )

            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Shared Progress",
                "heading_level": 1,
                "bullets": [
                    f"Current status: {update['status']}",
                    f"Next phase: {'WAITING_CUSTOMER_INPUT' if followup_questions else 'INVESTIGATING'}",
                    f"Intake category: {classification['category']}",
                    f"Intake urgency: {classification['urgency']}",
                ],
            }
            if incident_timeframe:
                progress_payload["bullets"].append(f"Incident timeframe: {incident_timeframe}")
            if missing_fields:
                progress_payload["bullets"].append(f"Missing fields: {', '.join(missing_fields)}")
            if update.get("customer_followup_answers"):
                progress_payload["bullets"].append(
                    f"Follow-up answers received: {len(cast(dict[str, dict[str, str]], update.get('customer_followup_answers') or {}))}"
                )
            if update.get("execution_mode") == "plan":
                if followup_questions:
                    progress_payload["bullets"].append("Planning note: plan モードだが、不足情報の確認が先に必要")
                else:
                    progress_payload["bullets"].append("Planning note: plan モードのため、次はユーザー承認待ちの案内を行う")
            self._invoke_tool(
                self.write_shared_memory_tool,
                case_id,
                workspace_path,
                context_payload,
                progress_payload,
            )

        if followup_questions:
            return cast("CaseState", update)

        update["intake_rework_required"] = False
        update["intake_rework_reason"] = ""
        update["intake_missing_fields"] = []
        update["intake_followup_questions"] = {}

        if update.get("execution_mode") == "plan":
            update["next_action"] = "ユーザーに計画を提示して承認を得る"
        else:
            update["next_action"] = "SuperVisorAgent が調査フェーズを開始する"
        return cast("CaseState", update)


def build_intake_agent_definition() -> AgentDefinition:
    return AgentDefinition(INTAKE_AGENT, "Triage and initialize the case", kind="phase", parent_role=SUPERVISOR_AGENT)