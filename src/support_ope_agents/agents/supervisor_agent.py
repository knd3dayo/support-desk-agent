from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState, WorkflowKind
    from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor


@dataclass(slots=True)
class SupervisorPhaseExecutor:
    read_shared_memory_tool: Callable[..., Any]
    write_shared_memory_tool: Callable[..., Any]
    log_analyzer_executor: "LogAnalyzerPhaseExecutor | None" = None

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
    def _parse_memory(raw_result: str) -> dict[str, str]:
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return {"context": "", "progress": "", "summary": ""}
        if not isinstance(parsed, dict):
            return {"context": "", "progress": "", "summary": ""}
        return {
            "context": str(parsed.get("context") or ""),
            "progress": str(parsed.get("progress") or ""),
            "summary": str(parsed.get("summary") or ""),
        }

    @staticmethod
    def _resolve_intake_category(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
        state_category = str(state.get("intake_category") or "").strip()
        if state_category:
            return state_category

        combined = "\n".join(memory_snapshot.values())
        match = re.search(r"(?:Category|Intake category):\s*([^\n]+)", combined)
        if match:
            return match.group(1).strip()
        return "ambiguous_case"

    @staticmethod
    def _resolve_intake_urgency(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
        state_urgency = str(state.get("intake_urgency") or "").strip()
        if state_urgency:
            return state_urgency

        combined = "\n".join(memory_snapshot.values())
        match = re.search(r"(?:Urgency|Intake urgency):\s*([^\n]+)", combined)
        if match:
            return match.group(1).strip()
        return "medium"

    @staticmethod
    def _planned_child_agents(category: str) -> list[str]:
        if category == "specification_inquiry":
            return ["KnowledgeRetrieverAgent"]
        if category == "incident_investigation":
            return ["LogAnalyzerAgent", "KnowledgeRetrieverAgent"]
        if category == "ambiguous_case":
            return ["LogAnalyzerAgent", "KnowledgeRetrieverAgent"]
        return ["KnowledgeRetrieverAgent"]

    @staticmethod
    def _resolve_effective_workflow_kind(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
        workflow_kind = str(state.get("workflow_kind") or "").strip()
        intake_category = SupervisorPhaseExecutor._resolve_intake_category(state, memory_snapshot)
        valid_values = {"specification_inquiry", "incident_investigation", "ambiguous_case"}

        if workflow_kind not in valid_values:
            return intake_category if intake_category in valid_values else "ambiguous_case"

        if workflow_kind == "ambiguous_case" and intake_category in {"specification_inquiry", "incident_investigation"}:
            return intake_category

        return workflow_kind

    @staticmethod
    def _resolve_incident_timeframe(state: "CaseState", memory_snapshot: dict[str, str]) -> str:
        timeframe = str(state.get("intake_incident_timeframe") or "").strip()
        if timeframe:
            return timeframe

        combined = "\n".join(memory_snapshot.values())
        match = re.search(r"Incident timeframe:\s*([^\n]+)", combined)
        if match:
            return match.group(1).strip()
        return ""

    def _validate_intake(self, state: "CaseState", memory_snapshot: dict[str, str]) -> tuple[list[str], str]:
        missing_fields: list[str] = []
        intake_category = self._resolve_intake_category(state, memory_snapshot)
        intake_urgency = self._resolve_intake_urgency(state, memory_snapshot)
        incident_timeframe = self._resolve_incident_timeframe(state, memory_snapshot)

        if not intake_category:
            missing_fields.append("intake_category")
        if not intake_urgency:
            missing_fields.append("intake_urgency")
        if intake_category == "incident_investigation" and not incident_timeframe:
            missing_fields.append("intake_incident_timeframe")

        if not missing_fields:
            return [], ""

        reasons = {
            "intake_category": "問い合わせ分類が未確定",
            "intake_urgency": "緊急度が未設定",
            "intake_incident_timeframe": "障害発生時間帯が未確認",
        }
        return missing_fields, "、".join(reasons[field_name] for field_name in missing_fields)

    def execute_investigation(self, state: CaseState) -> CaseState:
        update = cast("CaseState", dict(state))
        update["status"] = "INVESTIGATING"
        update["current_agent"] = SUPERVISOR_AGENT

        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        memory_snapshot = {"context": "", "progress": "", "summary": ""}
        if case_id and workspace_path:
            memory_snapshot = self._parse_memory(self._invoke_tool(self.read_shared_memory_tool, case_id, workspace_path))

        missing_fields, rework_reason = self._validate_intake(update, memory_snapshot)
        if missing_fields:
            update["status"] = "TRIAGED"
            update["current_agent"] = SUPERVISOR_AGENT
            update["intake_rework_required"] = True
            update["intake_rework_reason"] = rework_reason
            update["intake_missing_fields"] = missing_fields
            update["next_action"] = "IntakeAgent が不足情報の確認項目を作成し、ユーザー追加回答を待機する"

            if case_id and workspace_path:
                context_payload: SharedMemoryDocumentPayload = {
                    "title": "Supervisor Intake Gate",
                    "heading_level": 2,
                    "bullets": [
                        "Result: rework_required",
                        f"Reason: {rework_reason}",
                        f"Missing fields: {', '.join(missing_fields)}",
                    ],
                }
                progress_payload: SharedMemoryDocumentPayload = {
                    "title": "Supervisor Intake Gate",
                    "heading_level": 2,
                    "bullets": [
                        "Current phase: TRIAGED",
                        "Next phase: intake",
                        "Decision: return_to_intake",
                    ],
                }
                self._invoke_tool(
                    self.write_shared_memory_tool,
                    case_id,
                    workspace_path,
                    context_payload,
                    progress_payload,
                    None,
                    "append",
                )
            return cast("CaseState", update)

        update["intake_rework_required"] = False
        update["intake_rework_reason"] = ""
        update["intake_missing_fields"] = []

        intake_category = self._resolve_intake_category(update, memory_snapshot)
        intake_urgency = self._resolve_intake_urgency(update, memory_snapshot)
        effective_workflow_kind = self._resolve_effective_workflow_kind(update, memory_snapshot)
        planned_child_agents = self._planned_child_agents(effective_workflow_kind)
        log_analysis_summary = ""
        log_analysis_file = ""
        if self.log_analyzer_executor is not None and "LogAnalyzerAgent" in planned_child_agents:
            log_analysis = self.log_analyzer_executor.execute(update)
            log_analysis_summary = str(log_analysis.get("summary") or "")
            log_analysis_file = str(log_analysis.get("file") or "")
            if log_analysis_summary:
                update["log_analysis_summary"] = log_analysis_summary
            if log_analysis_file:
                update["log_analysis_file"] = log_analysis_file

        if update.get("execution_mode") == "action":
            default_summary = (
                "SuperVisorAgent は共有メモリを参照し、"
                f"{', '.join(planned_child_agents)} を使って調査を進めます。"
            )
            if log_analysis_summary:
                default_summary += f" ログ解析結果: {log_analysis_summary}"
            update["investigation_summary"] = str(update.get("investigation_summary") or default_summary)
        else:
            if not update.get("investigation_summary"):
                if effective_workflow_kind == "specification_inquiry":
                    update["investigation_summary"] = "仕様確認を優先し、KnowledgeRetrieverAgent 中心の調査計画を準備します。"
                elif effective_workflow_kind == "incident_investigation":
                    base_summary = "障害調査を優先し、LogAnalyzerAgent と KnowledgeRetrieverAgent の併用計画を準備します。"
                    if log_analysis_summary:
                        base_summary += f" 参考: {log_analysis_summary}"
                    update["investigation_summary"] = base_summary
                else:
                    update["investigation_summary"] = "仕様確認と障害調査の両面から、複合的な子エージェント起動計画を準備します。"

        if case_id and workspace_path:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Supervisor Investigation",
                "heading_level": 2,
                "bullets": [
                    f"Intake category: {intake_category}",
                    f"Intake urgency: {intake_urgency}",
                    f"Effective workflow kind: {effective_workflow_kind}",
                    f"Workflow kind: {str(update.get('workflow_kind') or '')}",
                    f"Execution mode: {str(update.get('execution_mode') or '')}",
                    f"Log analysis file: {log_analysis_file or 'n/a'}",
                    f"Log analysis summary: {log_analysis_summary or 'n/a'}",
                    f"Investigation summary: {str(update.get('investigation_summary') or '')}",
                ],
            }
            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Supervisor Investigation",
                "heading_level": 2,
                "bullets": [
                    "Current phase: INVESTIGATING",
                    f"Shared context loaded: {'yes' if memory_snapshot['context'].strip() else 'no'}",
                    f"Planned child agents: {', '.join(planned_child_agents)}",
                    f"Log analysis executed: {'yes' if log_analysis_summary else 'no'}",
                ],
            }
            self._invoke_tool(
                self.write_shared_memory_tool,
                case_id,
                workspace_path,
                context_payload,
                progress_payload,
                None,
                "append",
            )
        return cast("CaseState", update)

    def execute_draft_review(self, state: CaseState) -> CaseState:
        update = cast("CaseState", dict(state))
        update["status"] = "DRAFT_READY"
        update["current_agent"] = SUPERVISOR_AGENT

        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        memory_snapshot = {"context": "", "progress": "", "summary": ""}
        if case_id and workspace_path:
            memory_snapshot = self._parse_memory(self._invoke_tool(self.read_shared_memory_tool, case_id, workspace_path))

        intake_category = self._resolve_intake_category(update, memory_snapshot)
        intake_urgency = self._resolve_intake_urgency(update, memory_snapshot)
        effective_workflow_kind = self._resolve_effective_workflow_kind(update, memory_snapshot)
        review_focus = "表現の妥当性と根拠の整合性を確認する"
        if effective_workflow_kind == "incident_investigation":
            review_focus = "障害原因の断定過剰や不要な復旧約束がないかを重点確認する"
        elif effective_workflow_kind == "specification_inquiry":
            review_focus = "仕様説明の正確性と誤解を招く表現がないかを重点確認する"
        if intake_urgency == "high":
            review_focus += "。高優先度案件のため、簡潔で即応可能なドラフトを優先する"

        if update.get("execution_mode") == "plan":
            update["draft_response"] = (
                "plan モードでは SuperVisorAgent がドラフト作成とレビュー方針のみを返却し、"
                f"レビューでは「{review_focus}」を重視して action モードへ進みます。"
            )
        else:
            update.setdefault(
                "draft_response",
                f"action モードで SuperVisorAgent 配下のドラフト作成とレビューを開始します。レビュー重点: {review_focus}",
            )

        if case_id and workspace_path:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Supervisor Draft Review",
                "heading_level": 2,
                "bullets": [
                    f"Intake category: {intake_category}",
                    f"Intake urgency: {intake_urgency}",
                    f"Effective workflow kind: {effective_workflow_kind}",
                    f"Review focus: {review_focus}",
                    f"Draft response readiness: {str(update.get('draft_response') or '')}",
                    "Managed child agents: DraftWriterAgent, ComplianceReviewerAgent",
                ],
            }
            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Supervisor Draft Review",
                "heading_level": 2,
                "bullets": [
                    "Current phase: DRAFT_READY",
                    "Review loop owner: SuperVisorAgent",
                    "Next transition: wait_for_approval",
                ],
            }
            self._invoke_tool(
                self.write_shared_memory_tool,
                case_id,
                workspace_path,
                context_payload,
                progress_payload,
                None,
                "append",
            )
        return cast("CaseState", update)


def build_supervisor_agent_definition() -> AgentDefinition:
    return AgentDefinition(SUPERVISOR_AGENT, "Supervise the full support workflow", kind="supervisor")