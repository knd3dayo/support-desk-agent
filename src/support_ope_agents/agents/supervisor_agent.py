from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import BACK_SUPPORT_INQUIRY_WRITER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import EscalationSettings
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState, WorkflowKind
    from support_ope_agents.agents.back_support_escalation_agent import BackSupportEscalationPhaseExecutor
    from support_ope_agents.agents.back_support_inquiry_writer_agent import BackSupportInquiryWriterPhaseExecutor
    from support_ope_agents.agents.compliance_reviewer_agent import ComplianceReviewerPhaseExecutor
    from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
    from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
    from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor


@dataclass(slots=True)
class SupervisorPhaseExecutor:
    read_shared_memory_tool: Callable[..., Any]
    write_shared_memory_tool: Callable[..., Any]
    draft_writer_executor: "DraftWriterPhaseExecutor | None" = None
    log_analyzer_executor: "LogAnalyzerPhaseExecutor | None" = None
    knowledge_retriever_executor: "KnowledgeRetrieverPhaseExecutor | None" = None
    compliance_reviewer_executor: "ComplianceReviewerPhaseExecutor | None" = None
    back_support_escalation_executor: "BackSupportEscalationPhaseExecutor | None" = None
    back_support_inquiry_writer_executor: "BackSupportInquiryWriterPhaseExecutor | None" = None
    escalation_settings: EscalationSettings = field(default_factory=EscalationSettings)
    compliance_max_review_loops: int = 3

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

    def _collect_escalation_missing_artifacts(
        self,
        effective_workflow_kind: str,
        log_analysis_summary: str,
        memory_snapshot: dict[str, str],
    ) -> list[str]:
        missing_artifacts: list[str] = []
        combined = "\n".join(memory_snapshot.values()).lower()
        missing_artifacts.extend(self.escalation_settings.default_missing_artifacts_by_workflow.get(effective_workflow_kind, []))
        if any(marker in log_analysis_summary for marker in self.escalation_settings.missing_log_markers):
            missing_artifacts.append("解析対象ログファイル")
        if "stacktrace" in combined or "exception" in combined:
            missing_artifacts.append("例外発生時の完全なスタックトレース")

        deduplicated: list[str] = []
        for artifact in missing_artifacts:
            if artifact not in deduplicated:
                deduplicated.append(artifact)
        return deduplicated

    @staticmethod
    def _has_actionable_knowledge_evidence(
        knowledge_retrieval_summary: str,
        knowledge_retrieval_results: list[dict[str, object]],
        knowledge_retrieval_adopted_sources: list[str],
    ) -> bool:
        if knowledge_retrieval_adopted_sources:
            return True

        actionable_statuses = {"matched", "fetched"}
        for item in knowledge_retrieval_results:
            if str(item.get("status") or "").strip().lower() in actionable_statuses:
                return True

        return bool(knowledge_retrieval_summary.strip())

    def _decide_escalation(
        self,
        state: "CaseState",
        *,
        effective_workflow_kind: str,
        investigation_summary: str,
        log_analysis_summary: str,
        knowledge_retrieval_summary: str,
        knowledge_retrieval_results: list[dict[str, object]],
        knowledge_retrieval_adopted_sources: list[str],
        memory_snapshot: dict[str, str],
    ) -> tuple[bool, str, list[str]]:
        if bool(state.get("escalation_required")):
            reason = str(state.get("escalation_reason") or "調査結果だけでは確実な回答が困難")
            missing_artifacts = list(state.get("escalation_missing_artifacts") or [])
            return True, reason, missing_artifacts

        combined_text = "\n".join(
            part for part in [investigation_summary, log_analysis_summary, *memory_snapshot.values()] if part
        ).lower()
        has_uncertainty = any(marker.lower() in combined_text for marker in self.escalation_settings.uncertainty_markers)
        missing_logs = any(marker in log_analysis_summary for marker in self.escalation_settings.missing_log_markers)
        actionable_knowledge_evidence = self._has_actionable_knowledge_evidence(
            knowledge_retrieval_summary,
            knowledge_retrieval_results,
            knowledge_retrieval_adopted_sources,
        )

        if effective_workflow_kind == "incident_investigation" and missing_logs and not has_uncertainty and actionable_knowledge_evidence:
            return False, "", []

        if not has_uncertainty and not (effective_workflow_kind == "incident_investigation" and missing_logs):
            return False, "", []

        reason_parts: list[str] = []
        if has_uncertainty:
            reason_parts.append("調査結果から原因や仕様差分を確定できない")
        if missing_logs:
            reason_parts.append("必要なログが不足している")
        reason = "、".join(reason_parts) or "調査結果だけでは確実な回答が困難"
        missing_artifacts = self._collect_escalation_missing_artifacts(
            effective_workflow_kind,
            log_analysis_summary,
            memory_snapshot,
        )
        return True, reason, missing_artifacts

    @staticmethod
    def _build_escalation_summary(
        *,
        reason: str,
        investigation_summary: str,
        missing_artifacts: list[str],
    ) -> str:
        summary = f"エスカレーション理由: {reason}"
        if investigation_summary:
            summary += f" 調査要約: {investigation_summary}"
        if missing_artifacts:
            summary += f" 追加で必要な資料: {', '.join(missing_artifacts)}"
        return summary

    @staticmethod
    def _build_escalation_draft(
        *,
        reason: str,
        missing_artifacts: list[str],
        execution_mode: str,
    ) -> str:
        requested_items = "、".join(missing_artifacts) if missing_artifacts else "追加ログおよび再現情報"
        if execution_mode == "plan":
            return (
                "plan モードでは通常回答の代わりにエスカレーション案を返します。"
                f" 理由: {reason}。依頼予定項目: {requested_items}。"
            )
        return (
            "現時点では確実な回答に必要な情報が不足しているため、バックサポートへエスカレーションします。"
            f" 調査継続のため、{requested_items} の提供をご確認ください。"
        )

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+", " ", text.lower()).strip()

    @classmethod
    def _select_final_knowledge_source(cls, results: list[dict[str, object]], raw_issue: str = "") -> str:
        if not results:
            return ""

        normalized_query = cls._normalize_query_text(raw_issue)
        status_priority = {"matched": 3, "fetched": 2, "configured": 1}
        source_type_priority = {"document_source": 1, "ticket_source": 0}

        def _list_length(value: object) -> int:
            return len(value) if isinstance(value, list) else 0

        def _explicit_source_match(item: dict[str, object]) -> int:
            normalized_source_name = cls._normalize_query_text(str(item.get("source_name") or ""))
            return int(bool(normalized_query and normalized_source_name and normalized_source_name in normalized_query))

        ranked = sorted(
            results,
            key=lambda item: (
                _explicit_source_match(item),
                status_priority.get(str(item.get("status") or ""), -1),
                source_type_priority.get(str(item.get("source_type") or ""), -1),
                _list_length(item.get("evidence")),
                _list_length(item.get("matched_paths")),
            ),
            reverse=True,
        )
        best = ranked[0]
        if status_priority.get(str(best.get("status") or ""), -1) < 0:
            return ""
        return str(best.get("source_name") or "").strip()

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
        knowledge_retrieval_summary = ""
        knowledge_retrieval_results: list[dict[str, object]] = []
        knowledge_retrieval_adopted_sources: list[str] = []
        knowledge_retrieval_final_adopted_source = ""
        if self.log_analyzer_executor is not None and "LogAnalyzerAgent" in planned_child_agents:
            log_analysis = self.log_analyzer_executor.execute(update)
            log_analysis_summary = str(log_analysis.get("summary") or "")
            log_analysis_file = str(log_analysis.get("file") or "")
            if log_analysis_summary:
                update["log_analysis_summary"] = log_analysis_summary
            if log_analysis_file:
                update["log_analysis_file"] = log_analysis_file
        if self.knowledge_retriever_executor is not None and "KnowledgeRetrieverAgent" in planned_child_agents:
            knowledge_result = self.knowledge_retriever_executor.execute(update)
            knowledge_retrieval_summary = str(knowledge_result.get("knowledge_retrieval_summary") or "")
            raw_results = knowledge_result.get("knowledge_retrieval_results")
            if isinstance(raw_results, list):
                knowledge_retrieval_results = [item for item in raw_results if isinstance(item, dict)]
            raw_adopted_sources = knowledge_result.get("knowledge_retrieval_adopted_sources")
            if isinstance(raw_adopted_sources, list):
                knowledge_retrieval_adopted_sources = [str(item) for item in raw_adopted_sources if str(item).strip()]
            knowledge_retrieval_final_adopted_source = self._select_final_knowledge_source(
                knowledge_retrieval_results,
                raw_issue=str(update.get("raw_issue") or ""),
            )
            if knowledge_retrieval_summary:
                update["knowledge_retrieval_summary"] = knowledge_retrieval_summary
            if knowledge_retrieval_results:
                update["knowledge_retrieval_results"] = knowledge_retrieval_results
            update["knowledge_retrieval_adopted_sources"] = knowledge_retrieval_adopted_sources
            update["knowledge_retrieval_final_adopted_source"] = knowledge_retrieval_final_adopted_source

        if update.get("execution_mode") == "action":
            default_summary = (
                "SuperVisorAgent は共有メモリを参照し、"
                f"{', '.join(planned_child_agents)} を使って調査を進めます。"
            )
            if log_analysis_summary:
                default_summary += f" ログ解析結果: {log_analysis_summary}"
            if knowledge_retrieval_summary:
                default_summary += f" ナレッジ照会結果: {knowledge_retrieval_summary}"
            update["investigation_summary"] = str(update.get("investigation_summary") or default_summary)
        else:
            if not update.get("investigation_summary"):
                if effective_workflow_kind == "specification_inquiry":
                    base_summary = "仕様確認を優先し、KnowledgeRetrieverAgent 中心の調査計画を準備します。"
                    if knowledge_retrieval_summary:
                        base_summary += f" 参考: {knowledge_retrieval_summary}"
                    update["investigation_summary"] = base_summary
                elif effective_workflow_kind == "incident_investigation":
                    base_summary = "障害調査を優先し、LogAnalyzerAgent と KnowledgeRetrieverAgent の併用計画を準備します。"
                    if log_analysis_summary:
                        base_summary += f" 参考: {log_analysis_summary}"
                    if knowledge_retrieval_summary:
                        base_summary += f" ナレッジ候補: {knowledge_retrieval_summary}"
                    update["investigation_summary"] = base_summary
                else:
                    update["investigation_summary"] = "仕様確認と障害調査の両面から、複合的な子エージェント起動計画を準備します。"

        investigation_summary = str(update.get("investigation_summary") or "")
        escalation_required, escalation_reason, escalation_missing_artifacts = self._decide_escalation(
            update,
            effective_workflow_kind=effective_workflow_kind,
            investigation_summary=investigation_summary,
            log_analysis_summary=log_analysis_summary,
            knowledge_retrieval_summary=knowledge_retrieval_summary,
            knowledge_retrieval_results=knowledge_retrieval_results,
            knowledge_retrieval_adopted_sources=knowledge_retrieval_adopted_sources,
            memory_snapshot=memory_snapshot,
        )
        update["escalation_required"] = escalation_required
        update["escalation_reason"] = escalation_reason
        update["escalation_missing_artifacts"] = escalation_missing_artifacts
        if escalation_required:
            update["escalation_summary"] = self._build_escalation_summary(
                reason=escalation_reason,
                investigation_summary=investigation_summary,
                missing_artifacts=escalation_missing_artifacts,
            )
            update["next_action"] = "BackSupportEscalationAgent がエスカレーション材料を整理する"
        else:
            update["escalation_summary"] = ""
            update["next_action"] = "SuperVisorAgent がドラフト作成フェーズを開始する"

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
                    f"Knowledge retrieval summary: {knowledge_retrieval_summary or 'n/a'}",
                    f"Adopted knowledge sources: {', '.join(knowledge_retrieval_adopted_sources) if knowledge_retrieval_adopted_sources else 'n/a'}",
                    f"Final adopted knowledge source: {knowledge_retrieval_final_adopted_source or 'n/a'}",
                    f"Investigation summary: {str(update.get('investigation_summary') or '')}",
                    f"Escalation required: {'yes' if escalation_required else 'no'}",
                    f"Escalation reason: {escalation_reason or 'n/a'}",
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
                    f"Knowledge retrieval executed: {'yes' if knowledge_retrieval_summary or knowledge_retrieval_results else 'no'}",
                    f"Knowledge sources adopted: {', '.join(knowledge_retrieval_adopted_sources) if knowledge_retrieval_adopted_sources else 'none'}",
                    f"Final knowledge source: {knowledge_retrieval_final_adopted_source or 'none'}",
                    f"Escalation path selected: {'yes' if escalation_required else 'no'}",
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

    def execute_escalation_review(self, state: CaseState) -> CaseState:
        update = cast("CaseState", dict(state))
        update["status"] = "DRAFT_READY"
        update["current_agent"] = BACK_SUPPORT_INQUIRY_WRITER_AGENT

        if not bool(update.get("escalation_required")):
            update["escalation_required"] = True
            update["escalation_reason"] = str(update.get("escalation_reason") or "調査結果だけでは確実な回答が困難")

        if self.back_support_escalation_executor is not None:
            update.update(cast("CaseState", self.back_support_escalation_executor.execute(update)))
        else:
            missing_artifacts = list(update.get("escalation_missing_artifacts") or [])
            escalation_reason = str(update.get("escalation_reason") or "調査結果だけでは確実な回答が困難")
            investigation_summary = str(update.get("investigation_summary") or "")
            update["escalation_summary"] = self._build_escalation_summary(
                reason=escalation_reason,
                investigation_summary=investigation_summary,
                missing_artifacts=missing_artifacts,
            )

        if self.back_support_inquiry_writer_executor is not None:
            update.update(cast("CaseState", self.back_support_inquiry_writer_executor.execute(update)))
        else:
            update["escalation_draft"] = self._build_escalation_draft(
                reason=str(update.get("escalation_reason") or "調査結果だけでは確実な回答が困難"),
                missing_artifacts=list(update.get("escalation_missing_artifacts") or []),
                execution_mode=str(update.get("execution_mode") or ""),
            )
            update["draft_response"] = update["escalation_draft"]

        update["next_action"] = "エスカレーション問い合わせ文案を承認フェーズへ回付する"
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
            max_review_loops = max(1, int(self.compliance_max_review_loops))
            update["draft_review_max_loops"] = max_review_loops
            update["draft_review_iterations"] = 0
            if self.draft_writer_executor is not None:
                for attempt in range(1, max_review_loops + 1):
                    update["draft_review_iterations"] = attempt
                    draft_result = self.draft_writer_executor.execute(cast(dict[str, object], update))
                    update["draft_response"] = str(draft_result.get("draft_response") or update.get("draft_response") or "")

                    if self.compliance_reviewer_executor is None:
                        update["compliance_review_passed"] = True
                        update["next_action"] = "ApprovalAgent へドラフトを回付する"
                        break

                    compliance_review = self.compliance_reviewer_executor.execute(cast(dict[str, object], update))
                    update["compliance_review_summary"] = str(compliance_review.get("compliance_review_summary") or "")
                    update["compliance_review_results"] = cast(list[dict[str, object]], compliance_review.get("compliance_review_results") or [])
                    update["compliance_review_adopted_sources"] = cast(list[str], compliance_review.get("compliance_review_adopted_sources") or [])
                    update["compliance_review_issues"] = cast(list[str], compliance_review.get("compliance_review_issues") or [])
                    update["compliance_notice_present"] = bool(compliance_review.get("compliance_notice_present"))
                    update["compliance_notice_matched_phrase"] = str(compliance_review.get("compliance_notice_matched_phrase") or "")
                    update["compliance_revision_request"] = str(compliance_review.get("compliance_revision_request") or "")
                    update["compliance_review_passed"] = bool(compliance_review.get("compliance_review_passed"))
                    if bool(update.get("compliance_review_passed")):
                        update["next_action"] = "ApprovalAgent へドラフトを回付する"
                        break
                if not bool(update.get("compliance_review_passed")):
                    update["next_action"] = "最大レビュー回数に達しました。差戻し論点を確認して人手でドラフト修正要否を判断してください。"
            else:
                update.setdefault(
                    "draft_response",
                    f"action モードで SuperVisorAgent 配下のドラフト作成とレビューを開始します。レビュー重点: {review_focus}",
                )

        update["review_focus"] = review_focus

        if update.get("execution_mode") == "plan" and self.compliance_reviewer_executor is not None:
            compliance_review = self.compliance_reviewer_executor.execute(cast(dict[str, object], update))
            update["compliance_review_summary"] = str(compliance_review.get("compliance_review_summary") or "")
            update["compliance_review_results"] = cast(list[dict[str, object]], compliance_review.get("compliance_review_results") or [])
            update["compliance_review_adopted_sources"] = cast(list[str], compliance_review.get("compliance_review_adopted_sources") or [])
            update["compliance_review_issues"] = cast(list[str], compliance_review.get("compliance_review_issues") or [])
            update["compliance_notice_present"] = bool(compliance_review.get("compliance_notice_present"))
            update["compliance_notice_matched_phrase"] = str(compliance_review.get("compliance_notice_matched_phrase") or "")
            update["compliance_revision_request"] = str(compliance_review.get("compliance_revision_request") or "")
            update["compliance_review_passed"] = bool(compliance_review.get("compliance_review_passed"))
            if not bool(update.get("compliance_review_passed")):
                update["next_action"] = "DraftWriterAgent が修正観点を反映してドラフトを更新する"
            else:
                update["next_action"] = "ApprovalAgent へドラフトを回付する"

        if case_id and workspace_path:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Supervisor Draft Review",
                "heading_level": 2,
                "bullets": [
                    f"Intake category: {intake_category}",
                    f"Intake urgency: {intake_urgency}",
                    f"Effective workflow kind: {effective_workflow_kind}",
                    f"Review focus: {review_focus}",
                    f"Draft review loops: {str(update.get('draft_review_iterations') or 0)}/{str(update.get('draft_review_max_loops') or self.compliance_max_review_loops)}",
                    f"Draft response readiness: {str(update.get('draft_response') or '')}",
                    f"Compliance review summary: {str(update.get('compliance_review_summary') or 'n/a')}",
                    f"Compliance notice present: {'yes' if bool(update.get('compliance_notice_present')) else 'no'}",
                    f"Compliance adopted sources: {', '.join(cast(list[str], update.get('compliance_review_adopted_sources') or [])) or 'n/a'}",
                    "Managed child agents: DraftWriterAgent, ComplianceReviewerAgent",
                ],
            }
            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Supervisor Draft Review",
                "heading_level": 2,
                "bullets": [
                    "Current phase: DRAFT_READY",
                    "Review loop owner: SuperVisorAgent",
                    f"Review loop count: {str(update.get('draft_review_iterations') or 0)}/{str(update.get('draft_review_max_loops') or self.compliance_max_review_loops)}",
                    f"Compliance review passed: {'yes' if bool(update.get('compliance_review_passed')) else 'no'}",
                    f"Next transition: {str(update.get('next_action') or 'wait_for_approval')}",
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