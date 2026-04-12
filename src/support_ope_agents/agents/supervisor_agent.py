from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, cast

from support_ope_agents.agents.intake_agent import IntakeAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import BACK_SUPPORT_INQUIRY_WRITER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import EscalationSettings
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
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
    constraint_mode: str = "default"
    max_investigation_loops: int = 1

    def _runtime_constraints_enabled(self) -> bool:
        return self.constraint_mode in {"default", "runtime_only"}

    @staticmethod
    def passthrough_state(state: dict[str, object]) -> dict[str, object]:
        return dict(state)

    @staticmethod
    def route_after_investigation(state: dict[str, object]) -> str:
        if state.get("escalation_required"):
            return "escalation_review"
        return "draft_review"

    @staticmethod
    def route_entry(state: dict[str, object]) -> str:
        decision = str(state.get("approval_decision") or "").strip().lower()
        if decision in {"rejected", "reject"}:
            return "draft_review"
        return "investigation"

    def create_node(self):
        from langgraph.graph import END, START, StateGraph
        from support_ope_agents.workflow.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node(
            "supervisor_entry",
            lambda state: cast(CaseState, self.passthrough_state(cast(dict[str, object], state))),
        )
        graph.add_node("investigation", self.execute_investigation)
        graph.add_node("draft_review", self.execute_draft_review)
        graph.add_node("escalation_review", self.execute_escalation_review)
        graph.add_edge(START, "supervisor_entry")
        graph.add_conditional_edges(
            "supervisor_entry",
            lambda state: self.route_entry(cast(dict[str, object], state)),
            {
                "investigation": "investigation",
                "draft_review": "draft_review",
            },
        )
        graph.add_conditional_edges(
            "investigation",
            lambda state: self.route_after_investigation(cast(dict[str, object], state)),
            {
                "escalation_review": "escalation_review",
                "draft_review": "draft_review",
            },
        )
        graph.add_edge("draft_review", END)
        graph.add_edge("escalation_review", END)
        return graph.compile()

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
        result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(cast(Any, result))
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
    def _planned_child_agents(category: str) -> list[str]:
        if category == "specification_inquiry":
            return ["KnowledgeRetrieverAgent"]
        if category == "incident_investigation":
            return ["LogAnalyzerAgent", "KnowledgeRetrieverAgent"]
        if category == "ambiguous_case":
            return ["LogAnalyzerAgent", "KnowledgeRetrieverAgent"]
        return ["KnowledgeRetrieverAgent"]

    @staticmethod
    def _merge_unique_lines(base_text: str, extra_text: str) -> str:
        normalized_base = base_text.strip()
        normalized_extra = extra_text.strip()
        if not normalized_base:
            return normalized_extra
        if not normalized_extra or normalized_extra in normalized_base:
            return normalized_base
        return f"{normalized_base} 追加調査: {normalized_extra}".strip()

    @staticmethod
    def _merge_unique_items(base_items: list[str], extra_items: list[str]) -> list[str]:
        merged: list[str] = []
        for item in [*base_items, *extra_items]:
            normalized = str(item).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged

    @staticmethod
    def _merge_knowledge_results(
        base_results: list[dict[str, object]],
        extra_results: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in [*base_results, *extra_results]:
            try:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
            except TypeError:
                marker = str(item)
            if marker in seen:
                continue
            merged.append(item)
            seen.add(marker)
        return merged

    @staticmethod
    def _extract_followup_clues(
        *,
        raw_issue: str,
        log_analysis_summary: str,
        knowledge_retrieval_summary: str,
        knowledge_retrieval_results: list[dict[str, object]],
        existing_notes: list[str],
    ) -> list[str]:
        candidates: list[str] = []
        combined_baseline = "\n".join([raw_issue, *existing_notes]).lower()
        combined_findings = "\n".join([log_analysis_summary, knowledge_retrieval_summary])

        for match in re.findall(r"\b[\w.$-]+(?:Exception|Error)\b", combined_findings):
            candidates.append(match)
        for match in re.findall(r"Data source\s+[\w.$-]+\s+not found", combined_findings, flags=re.IGNORECASE):
            candidates.append(match)

        for item in knowledge_retrieval_results:
            status = str(item.get("status") or "").strip().lower()
            source_type = str(item.get("source_type") or "").strip().lower()
            source_name = str(item.get("source_name") or "").strip()
            if source_name and status in {"matched", "fetched"} and source_type == "document_source":
                candidates.append(source_name)
            evidence = item.get("evidence")
            if isinstance(evidence, list):
                for detail in evidence:
                    normalized = str(detail).strip()
                    if 4 <= len(normalized) <= 80:
                        candidates.append(normalized)
                        break

        normalized_candidates: list[str] = []
        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", str(candidate).strip())
            if len(normalized) < 4:
                continue
            if normalized.lower() in combined_baseline:
                continue
            if normalized not in normalized_candidates:
                normalized_candidates.append(normalized)
            if len(normalized_candidates) >= 4:
                break
        return normalized_candidates

    @staticmethod
    def _build_followup_instruction(clues: list[str]) -> str:
        if not clues:
            return ""
        return f"新しく判明した事実: {', '.join(clues)}。これらを起点に追加調査してください。"

    @staticmethod
    def _first_sentence(text: str, default: str) -> str:
        normalized = re.sub(r"\s+", " ", text.strip())
        if not normalized:
            return default
        for separator in ("。", "\n"):
            if separator in normalized:
                head = normalized.split(separator, 1)[0].strip()
                if head:
                    return head + ("。" if separator == "。" else "")
        return normalized

    @staticmethod
    def _extract_primary_issue(investigation_summary: str, log_analysis_summary: str) -> str:
        combined = "\n".join([investigation_summary, log_analysis_summary])
        data_source_match = re.search(r"Data source\s+([\w.$-]+)\s+not found", combined, flags=re.IGNORECASE)
        if data_source_match:
            return f"主要異常候補は Data source {data_source_match.group(1)} not found です。"

        exception_line_match = re.search(r"検出した例外候補[:：]\s*([^。]+)", combined)
        if exception_line_match:
            first_exception = exception_line_match.group(1).split(",", 1)[0].strip()
            if first_exception:
                return f"主要異常候補は {first_exception} です。"

        exception_name_match = re.search(r"\b([\w.$]+(?:Exception|Error))\b", combined)
        if exception_name_match:
            return f"主要異常候補は {exception_name_match.group(1)} です。"

        return ""

    @staticmethod
    def _extract_primary_evidence(investigation_summary: str, log_analysis_summary: str) -> str:
        combined = "\n".join([investigation_summary, log_analysis_summary])
        exception_line_match = re.search(r"代表的な例外行[:：]\s*([^。]+)", combined)
        if exception_line_match:
            return exception_line_match.group(1).strip()

        abnormal_line_match = re.search(r"代表的な異常行[:：]\s*([^。]+)", combined)
        if abnormal_line_match:
            return abnormal_line_match.group(1).strip()

        return ""

    @staticmethod
    def _summarize_next_action(next_action: str, escalation_required: bool) -> str:
        if escalation_required:
            return next_action or "バックサポート連携の準備を進めます。"
        if not next_action or "ドラフト作成フェーズ" in next_action:
            return "調査結果を回答ドラフトへ反映します。"
        return next_action

    @staticmethod
    def _summarize_primary_source(knowledge_retrieval_final_adopted_source: str, log_analysis_summary: str) -> str:
        if log_analysis_summary.strip():
            return "log analysis"
        if knowledge_retrieval_final_adopted_source.strip():
            return knowledge_retrieval_final_adopted_source
        return "investigation summary"

    def _build_summary_payload(
        self,
        *,
        investigation_summary: str,
        escalation_required: bool,
        escalation_reason: str,
        next_action: str,
        followup_notes: list[str],
        knowledge_retrieval_final_adopted_source: str,
        log_analysis_summary: str,
    ) -> SharedMemoryDocumentPayload:
        inferred_conclusion = self._extract_primary_issue(investigation_summary, log_analysis_summary)
        conclusion = "バックサポート連携が必要です。" if escalation_required else (
            inferred_conclusion or self._first_sentence(investigation_summary, "調査結果を整理し、回答ドラフト作成へ進めます。")
        )
        inferred_evidence = self._extract_primary_evidence(investigation_summary, log_analysis_summary)
        rationale = escalation_reason.strip() or inferred_evidence or self._first_sentence(
            log_analysis_summary or investigation_summary,
            "主要な調査根拠は investigation_summary を参照してください。",
        )
        bullets = [
            f"Conclusion: {conclusion}",
            f"Judgment rationale: {rationale}",
            f"Next action: {self._summarize_next_action(next_action, escalation_required)}",
            (
                "Primary source: "
                f"{self._summarize_primary_source(knowledge_retrieval_final_adopted_source, log_analysis_summary)}"
            ),
        ]
        if followup_notes:
            bullets.append(f"Follow-up investigation: {' | '.join(followup_notes)}")
        return {
            "title": "Supervisor Summary",
            "heading_level": 2,
            "bullets": bullets,
        }

    def _validate_intake(self, state: "CaseState", memory_snapshot: dict[str, str]) -> tuple[list[str], str]:
        result = IntakeAgent.validate_intake(state, memory_snapshot)
        return result.missing_fields, result.rework_reason

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
    def _sanitize_customer_facing_text(text: str) -> str:
        sanitized = str(text or "").strip()
        replacements = {
            "KnowledgeRetrieverAgent は問い合わせ内容をもとに document_sources を検索しました。": "関連資料も確認しました。",
            "KnowledgeRetrieverAgent": "関連資料",
            "LogAnalyzerAgent": "ログ解析",
            "SuperVisorAgent": "今回の調査",
            "document_sources": "関連資料",
            "共有メモリ": "調査メモ",
            "ナレッジ照会結果": "関連資料の確認結果",
            "ログ解析結果": "ログ確認結果",
        }
        for source, target in replacements.items():
            sanitized = sanitized.replace(source, target)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized

    @classmethod
    def _extract_customer_facing_knowledge_summary(
        cls,
        *,
        raw_issue: str,
        knowledge_retrieval_results: list[dict[str, object]],
        knowledge_retrieval_summary: str,
        final_source: str,
        workflow_kind: str,
    ) -> str:
        if not knowledge_retrieval_results:
            return ""

        normalized_query = cls._normalize_query_text(raw_issue)
        prioritized: list[dict[str, object]] = []
        if final_source:
            prioritized.extend(item for item in knowledge_retrieval_results if str(item.get("source_name") or "") == final_source)
        prioritized.extend(item for item in knowledge_retrieval_results if item not in prioritized)

        for item in prioritized:
            source_name = str(item.get("source_name") or "").strip()
            source_type = str(item.get("source_type") or "").strip()
            status = str(item.get("status") or "").strip()
            if status not in {"matched", "fetched", "hydrated"}:
                continue

            normalized_source = cls._normalize_query_text(source_name)
            explicit_match = bool(normalized_query and normalized_source and normalized_source in normalized_query)
            if workflow_kind == "incident_investigation" and source_type == "document_source" and not explicit_match:
                continue

            summary = cls._sanitize_customer_facing_text(str(item.get("summary") or ""))
            evidence = cast(list[object], item.get("evidence") or []) if isinstance(item.get("evidence"), list) else []
            highlight = next((str(entry).strip() for entry in evidence if str(entry).strip()), "")
            if summary:
                return summary
            if highlight:
                prefix = f"{source_name} では" if source_name else "関連資料では"
                return f"{prefix}{highlight} を確認しました。"

        if workflow_kind != "incident_investigation":
            return cls._sanitize_customer_facing_text(knowledge_retrieval_summary)
        return ""

    def _build_customer_facing_investigation_summary(
        self,
        *,
        raw_issue: str,
        workflow_kind: str,
        log_analysis_summary: str,
        knowledge_retrieval_summary: str,
        knowledge_retrieval_results: list[dict[str, object]],
        final_source: str,
    ) -> str:
        fragments: list[str] = []
        if log_analysis_summary:
            fragments.append(
                self._sanitize_customer_facing_text(log_analysis_summary)
                if self._runtime_constraints_enabled()
                else log_analysis_summary.strip()
            )

        knowledge_summary = self._extract_customer_facing_knowledge_summary(
            raw_issue=raw_issue,
            knowledge_retrieval_results=knowledge_retrieval_results,
            knowledge_retrieval_summary=knowledge_retrieval_summary,
            final_source=final_source,
            workflow_kind=workflow_kind,
        )
        if knowledge_summary and not self._runtime_constraints_enabled() and knowledge_retrieval_summary.strip():
            knowledge_summary = knowledge_retrieval_summary.strip()
        if knowledge_summary:
            fragments.append(knowledge_summary)

        if fragments:
            return " ".join(fragment for fragment in fragments if fragment).strip()

        if workflow_kind == "incident_investigation":
            return "添付ログと関連情報を確認し、現時点で把握できる異常内容を整理しました。"
        if workflow_kind == "specification_inquiry":
            return "関連資料を確認し、ご質問に対して回答可能な仕様情報を整理しました。"
        return "問い合わせ内容に関連する資料とログを確認し、回答に必要な情報を整理しました。"

    @staticmethod
    def _is_non_actionable_compliance_feedback(
        summary: str,
        issues: list[str],
        revision_request: str,
    ) -> bool:
        combined = "\n".join([summary, *issues, revision_request]).lower()
        if not combined.strip():
            return False
        blocking_markers = ["ポリシー文書を取得できませんでした", "document_sources", "確認根拠となるポリシー文書"]
        return any(marker.lower() in combined for marker in blocking_markers)

    @staticmethod
    def _summarize_text(text: str, limit: int = 220) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "").strip())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1].rstrip() + "…"

    @classmethod
    def _append_compliance_review_history(
        cls,
        state: "CaseState",
        *,
        iteration: int,
        review_focus: str,
        addressed_revision_request: str,
        draft_response: str,
        compliance_review_summary: str,
        compliance_review_issues: list[str],
        compliance_revision_request: str,
        compliance_review_passed: bool,
        compliance_review_adopted_sources: list[str],
        compliance_notice_present: bool,
    ) -> None:
        history = [item for item in cast(list[dict[str, object]], state.get("compliance_review_history") or []) if isinstance(item, dict)]
        history.append(
            {
                "iteration": iteration,
                "review_focus": review_focus,
                "addressed_revision_request": addressed_revision_request,
                "draft_response": draft_response,
                "draft_excerpt": cls._summarize_text(draft_response),
                "compliance_review_summary": compliance_review_summary,
                "compliance_review_issues": list(compliance_review_issues),
                "compliance_revision_request": compliance_revision_request,
                "passed": compliance_review_passed,
                "adopted_sources": list(compliance_review_adopted_sources),
                "notice_present": compliance_notice_present,
            }
        )
        state["compliance_review_history"] = history

    @classmethod
    def _latest_compliance_history_bullets(cls, state: "CaseState") -> list[str]:
        history = [item for item in cast(list[dict[str, object]], state.get("compliance_review_history") or []) if isinstance(item, dict)]
        if not history:
            return []
        latest = history[-1]
        issues = [str(item).strip() for item in cast(list[object], latest.get("compliance_review_issues") or []) if str(item).strip()]
        latest_revision_request = str(latest.get("compliance_revision_request") or "").strip()
        addressed_revision_request = str(latest.get("addressed_revision_request") or "").strip()
        draft_excerpt = str(latest.get("draft_excerpt") or "").strip()
        bullets = [f"Compliance review history entries: {len(history)}"]
        if addressed_revision_request:
            bullets.append(f"Latest compliance addressed request: {cls._summarize_text(addressed_revision_request)}")
        if issues:
            bullets.append(f"Latest compliance issues: {' | '.join(issues)}")
        if latest_revision_request:
            bullets.append(f"Latest compliance revision request: {cls._summarize_text(latest_revision_request)}")
        if draft_excerpt:
            bullets.append(f"Latest compliance response draft: {draft_excerpt}")
        return bullets

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
        update["intake_rework_required"] = False
        update["intake_rework_reason"] = ""
        update["intake_missing_fields"] = []

        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        memory_snapshot = {"context": "", "progress": "", "summary": ""}
        if case_id and workspace_path:
            memory_snapshot = self._parse_memory(self._invoke_tool(self.read_shared_memory_tool, case_id, workspace_path))

        intake_category = IntakeAgent.resolve_intake_category(update, memory_snapshot)
        intake_urgency = IntakeAgent.resolve_intake_urgency(update, memory_snapshot)
        effective_workflow_kind = IntakeAgent.resolve_effective_workflow_kind(update, memory_snapshot)
        planned_child_agents = self._planned_child_agents(effective_workflow_kind)
        log_analysis_summary = ""
        log_analysis_file = ""
        knowledge_retrieval_summary = ""
        knowledge_retrieval_results: list[dict[str, object]] = []
        knowledge_retrieval_adopted_sources: list[str] = []
        knowledge_retrieval_final_adopted_source = ""
        followup_notes: list[str] = []
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

        for _ in range(max(self.max_investigation_loops, 0)):
            followup_clues = self._extract_followup_clues(
                raw_issue=str(update.get("raw_issue") or ""),
                log_analysis_summary=log_analysis_summary,
                knowledge_retrieval_summary=knowledge_retrieval_summary,
                knowledge_retrieval_results=knowledge_retrieval_results,
                existing_notes=followup_notes,
            )
            followup_instruction = self._build_followup_instruction(followup_clues)
            if not followup_instruction:
                break
            followup_notes.append(followup_instruction)

            followup_state = cast("CaseState", dict(update))
            followup_state["raw_issue"] = " ".join(
                part
                for part in [
                    str(update.get("raw_issue") or "").strip(),
                    str(update.get("intake_investigation_focus") or "").strip(),
                    followup_instruction,
                ]
                if part
            )

            if self.log_analyzer_executor is not None and "LogAnalyzerAgent" in planned_child_agents:
                followup_log_analysis = self.log_analyzer_executor.execute(followup_state)
                log_analysis_summary = self._merge_unique_lines(
                    log_analysis_summary,
                    str(followup_log_analysis.get("summary") or ""),
                )
                followup_file = str(followup_log_analysis.get("file") or "")
                if followup_file:
                    log_analysis_file = followup_file
                if log_analysis_summary:
                    update["log_analysis_summary"] = log_analysis_summary
                if log_analysis_file:
                    update["log_analysis_file"] = log_analysis_file

            if self.knowledge_retriever_executor is not None and "KnowledgeRetrieverAgent" in planned_child_agents:
                followup_knowledge_result = self.knowledge_retriever_executor.execute(followup_state)
                followup_summary = str(followup_knowledge_result.get("knowledge_retrieval_summary") or "")
                log_aware_summary = self._merge_unique_lines(knowledge_retrieval_summary, followup_summary)
                if log_aware_summary:
                    knowledge_retrieval_summary = log_aware_summary
                    update["knowledge_retrieval_summary"] = knowledge_retrieval_summary

                raw_followup_results = followup_knowledge_result.get("knowledge_retrieval_results")
                followup_results = [item for item in raw_followup_results if isinstance(item, dict)] if isinstance(raw_followup_results, list) else []
                if followup_results:
                    knowledge_retrieval_results = self._merge_knowledge_results(knowledge_retrieval_results, followup_results)
                    update["knowledge_retrieval_results"] = knowledge_retrieval_results

                raw_followup_sources = followup_knowledge_result.get("knowledge_retrieval_adopted_sources")
                followup_sources = [str(item) for item in raw_followup_sources if str(item).strip()] if isinstance(raw_followup_sources, list) else []
                knowledge_retrieval_adopted_sources = self._merge_unique_items(
                    knowledge_retrieval_adopted_sources,
                    followup_sources,
                )
                update["knowledge_retrieval_adopted_sources"] = knowledge_retrieval_adopted_sources
                knowledge_retrieval_final_adopted_source = self._select_final_knowledge_source(
                    knowledge_retrieval_results,
                    raw_issue=str(update.get("raw_issue") or ""),
                )
                update["knowledge_retrieval_final_adopted_source"] = knowledge_retrieval_final_adopted_source

        update["investigation_followup_loops"] = len(followup_notes)
        update["supervisor_followup_notes"] = followup_notes

        if update.get("execution_mode") == "action":
            default_summary = self._build_customer_facing_investigation_summary(
                raw_issue=str(update.get("raw_issue") or ""),
                workflow_kind=effective_workflow_kind,
                log_analysis_summary=log_analysis_summary,
                knowledge_retrieval_summary=knowledge_retrieval_summary,
                knowledge_retrieval_results=knowledge_retrieval_results,
                final_source=knowledge_retrieval_final_adopted_source,
            )
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
                    f"Follow-up investigation loops: {len(followup_notes)}",
                    f"Follow-up instructions: {' | '.join(followup_notes) if followup_notes else 'n/a'}",
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
                    f"Follow-up investigation loops: {len(followup_notes)}",
                    f"Follow-up instructions issued: {'yes' if followup_notes else 'no'}",
                    f"Escalation path selected: {'yes' if escalation_required else 'no'}",
                ],
            }
            summary_payload = self._build_summary_payload(
                investigation_summary=str(update.get("investigation_summary") or ""),
                escalation_required=escalation_required,
                escalation_reason=escalation_reason,
                next_action=str(update.get("next_action") or ""),
                followup_notes=followup_notes,
                knowledge_retrieval_final_adopted_source=knowledge_retrieval_final_adopted_source,
                log_analysis_summary=log_analysis_summary,
            )
            self._invoke_tool(
                self.write_shared_memory_tool,
                case_id,
                workspace_path,
                context_payload,
                progress_payload,
                summary_payload,
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
        update.setdefault("compliance_review_history", [])

        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        memory_snapshot = {"context": "", "progress": "", "summary": ""}
        if case_id and workspace_path:
            memory_snapshot = self._parse_memory(self._invoke_tool(self.read_shared_memory_tool, case_id, workspace_path))

        intake_category = IntakeAgent.resolve_intake_category(update, memory_snapshot)
        intake_urgency = IntakeAgent.resolve_intake_urgency(update, memory_snapshot)
        effective_workflow_kind = IntakeAgent.resolve_effective_workflow_kind(update, memory_snapshot)
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
                pending_revision_request = str(update.get("compliance_revision_request") or "").strip()
                for attempt in range(1, max_review_loops + 1):
                    update["draft_review_iterations"] = attempt
                    addressed_revision_request = pending_revision_request
                    draft_result = self.draft_writer_executor.execute(cast(dict[str, object], update))
                    update["draft_response"] = str(draft_result.get("draft_response") or update.get("draft_response") or "")

                    if self.compliance_reviewer_executor is None:
                        update["compliance_review_passed"] = True
                        self._append_compliance_review_history(
                            update,
                            iteration=attempt,
                            review_focus=review_focus,
                            addressed_revision_request=addressed_revision_request,
                            draft_response=str(update.get("draft_response") or ""),
                            compliance_review_summary="コンプライアンスレビューは未実施です。",
                            compliance_review_issues=[],
                            compliance_revision_request="",
                            compliance_review_passed=True,
                            compliance_review_adopted_sources=[],
                            compliance_notice_present=bool(update.get("compliance_notice_present")),
                        )
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
                    if (
                        not bool(update.get("compliance_review_passed"))
                        and self._is_non_actionable_compliance_feedback(
                            str(update.get("compliance_review_summary") or ""),
                            cast(list[str], update.get("compliance_review_issues") or []),
                            str(update.get("compliance_revision_request") or ""),
                        )
                        and str(update.get("draft_response") or "").strip()
                    ):
                        update["compliance_review_passed"] = True
                        update["compliance_review_summary"] = (
                            str(update.get("compliance_review_summary") or "")
                            + " ポリシー根拠の取得は未完了ですが、サポート担当者向けの調査回答としては継続可能と判断しました。"
                        ).strip()
                    self._append_compliance_review_history(
                        update,
                        iteration=attempt,
                        review_focus=review_focus,
                        addressed_revision_request=addressed_revision_request,
                        draft_response=str(update.get("draft_response") or ""),
                        compliance_review_summary=str(update.get("compliance_review_summary") or ""),
                        compliance_review_issues=cast(list[str], update.get("compliance_review_issues") or []),
                        compliance_revision_request=str(update.get("compliance_revision_request") or ""),
                        compliance_review_passed=bool(update.get("compliance_review_passed")),
                        compliance_review_adopted_sources=cast(list[str], update.get("compliance_review_adopted_sources") or []),
                        compliance_notice_present=bool(update.get("compliance_notice_present")),
                    )
                    pending_revision_request = str(update.get("compliance_revision_request") or "").strip()
                    if (
                        bool(update.get("compliance_review_passed"))
                        and self._is_non_actionable_compliance_feedback(
                            str(update.get("compliance_review_summary") or ""),
                            cast(list[str], update.get("compliance_review_issues") or []),
                            str(update.get("compliance_revision_request") or ""),
                        )
                    ):
                        update["next_action"] = "ApprovalAgent へドラフトを回付する"
                        break
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
                    *self._latest_compliance_history_bullets(update),
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
                    *self._latest_compliance_history_bullets(update),
                ],
            }
            compliance_review_issues = [
                str(item).strip() for item in cast(list[str], update.get('compliance_review_issues') or []) if str(item).strip()
            ]
            if compliance_review_issues:
                context_payload["bullets"].append(
                    f"Compliance review issues: {' | '.join(compliance_review_issues)}"
                )
                progress_payload["bullets"].append(
                    f"Compliance review issues: {' | '.join(compliance_review_issues)}"
                )
            compliance_revision_request = str(update.get('compliance_revision_request') or '').strip()
            if compliance_revision_request:
                context_payload["bullets"].append(f"Compliance revision request: {compliance_revision_request}")
                progress_payload["bullets"].append(f"Compliance revision request: {compliance_revision_request}")
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