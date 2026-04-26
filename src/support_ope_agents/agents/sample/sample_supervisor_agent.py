from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INVESTIGATE_AGENT
from support_ope_agents.agents.roles import SUPERVISOR_AGENT
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.util.asyncio_utils import run_awaitable_sync
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.util.formatting import format_result, format_ticket_context
from support_ope_agents.util.workspace_evidence import find_attachment_files, find_evidence_log_file

from support_ope_agents.agents.sample.sample_back_support_escalation_agent import SampleBackSupportEscalationAgent
from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_ope_agents.models.state import CaseState
from support_ope_agents.instructions import InstructionLoader


class SampleSupervisorAgent(AbstractAgent):
    def __init__(
        self,
        config: Any,
        investigate_executor: "SampleInvestigateAgent | None" = None,
        back_support_escalation_executor: "SampleBackSupportEscalationAgent | None" = None,
    ):
        from support_ope_agents.tools.registry import ToolRegistry
        self.config = config
        self.tool_registry = ToolRegistry(config)
        self.investigate_executor = investigate_executor
        self.back_support_escalation_executor = back_support_escalation_executor



    @staticmethod
    def _extract_investigation_summary(result: Any) -> str:
        return extract_result_output_text(result) or format_result(result)

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

    @staticmethod
    def _should_escalate(state: dict[str, Any]) -> bool:
        if bool(state.get("escalation_required")):
            return True
        raw_issue = str(state.get("raw_issue") or "").lower()
        escalation_markers = ("escalate", "escalation", "エスカレーション", "バックサポート", "unsupported")
        return any(marker in raw_issue for marker in escalation_markers)

    @staticmethod
    def _fallback_investigation_summary(raw_issue: str) -> str:
        if raw_issue:
            return f"サンプル調査結果: 問い合わせ内容を確認しました。要点は「{raw_issue}」です。"
        return "サンプル調査結果: 問い合わせ内容を確認しました。"

    def _build_draft_response(self, investigation_summary: str) -> str:
        summary = investigation_summary.strip() or "サンプル調査を実行しました。"
        return f"お問い合わせありがとうございます。\n\n{summary}\n\n必要であれば追加の確認事項もご案内できます。"

    @staticmethod
    def _format_followup_answers(state: "CaseState") -> str:
        answers = cast(dict[str, Any], state.get("customer_followup_answers") or {})
        if not answers:
            return ""

        lines: list[str] = []
        for key, record in answers.items():
            if not isinstance(record, dict):
                continue
            answer = str(record.get("answer") or "").strip()
            if not answer:
                continue
            question = str(record.get("question") or "").strip()
            if question:
                lines.append(f"- {key}: question={question} / answer={answer}")
            else:
                lines.append(f"- {key}: {answer}")
        if not lines:
            return ""
        return "追加確認への回答:\n" + "\n".join(lines)

    # チケット文脈の整形は共通ユーティリティに移動

    @staticmethod
    def _has_ticket_followup_answer(state: "CaseState") -> bool:
        answers = cast(dict[str, Any], state.get("customer_followup_answers") or {})
        return any("ticket" in str(key) for key in answers)

    @staticmethod
    def _format_shared_memory_snapshot(memory: dict[str, str]) -> str:
        sections: list[str] = []
        for key, label in (("context", "共有メモリ context"), ("progress", "共有メモリ progress"), ("summary", "共有メモリ summary")):
            value = str(memory.get(key) or "").strip()
            if not value:
                continue
            sections.append(f"{label}:\n{value}")
        return "\n\n".join(sections)

    def _build_investigation_query(self, state: "CaseState") -> str:
        raw_issue = str(state.get("raw_issue") or "").strip()
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        followup_section = self._format_followup_answers(state)
        ticket_context_section = format_ticket_context(cast(dict, state))
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        shared_memory = self.tool_registry.read_shared_memory_for_case(case_id, workspace_path, role=SUPERVISOR_AGENT)
        shared_memory_section = self._format_shared_memory_snapshot(shared_memory)
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        investigate_working_memory = self.tool_registry.read_investigate_working_memory_for_case(case_id, workspace_path, role=SUPERVISOR_AGENT)
        working_memory_params_section = (
            "\n".join(
                [
                    "Working memory tool parameters:",
                    f"- case_id: {case_id}",
                    f"- workspace_path: {workspace_path}",
                ]
            )
            if case_id and workspace_path
            else ""
        )
        investigate_working_memory_section = (
            f"Investigate working memory:\n{investigate_working_memory}"
            if investigate_working_memory
            else ""
        )
        incident_timeframe = str(state.get("intake_incident_timeframe") or "").strip()
        range_start = str(state.get("log_extract_range_start") or "").strip()
        range_end = str(state.get("log_extract_range_end") or "").strip()
        log_range_section = (
            "\n".join(
                part
                for part in (
                    "ログ抽出の手掛かり:",
                    f"- incident timeframe: {incident_timeframe}" if incident_timeframe else "",
                    f"- requested extract range: {range_start} -> {range_end}" if range_start and range_end else "",
                )
                if part
            )
            if incident_timeframe or (range_start and range_end)
            else ""
        )
        evidence_path = str(state.get("investigation_evidence_log_path") or "").strip()
        evidence_section = (
            "\n".join(
                [
                    "workspace 上の evidence ログが存在します。",
                    f"Evidence file: {Path(evidence_path).name}",
                    f"Evidence path: {evidence_path}",
                ]
            )
            if evidence_path
            else ""
        )
        attachment_paths = [str(path).strip() for path in list(state.get("investigation_attachment_paths") or []) if str(path).strip()]
        attachment_section = (
            "\n".join(
                [
                    "調査可能な添付ファイル path:",
                    *[f"- {path}" for path in attachment_paths],
                    "添付の利用順序: まず path を確認し、PDF は analyze_pdf_files、画像は analyze_image_files を優先してください。",
                ]
            )
            if attachment_paths
            else ""
        )

        extra_sections = [
            section
            for section in (
                working_memory_params_section,
                followup_section,
                ticket_context_section,
                shared_memory_section,
                investigate_working_memory_section,
                log_range_section,
                evidence_section,
                attachment_section,
            )
            if section
        ]
        if not extra_sections:
            return raw_issue

        preface = ""
        if self._has_ticket_followup_answer(state) and ticket_context_section:
            preface = (
                "追加確認でチケット候補への回答が返っています。"
                "取得済みチケット情報を優先して確認し、現在状況と次アクションをユーザー向けに整理してください。"
            )

        parts = [part for part in (preface, f"元の問い合わせ:\n{raw_issue}" if raw_issue else "", *extra_sections) if part]
        return "\n\n".join(parts)

    @staticmethod
    def _collect_adopted_sources(state: "CaseState") -> list[str]:
        adopted_sources: list[str] = []

        for value in cast(list[str], state.get("knowledge_retrieval_adopted_sources") or []):
            normalized = str(value).strip()
            if normalized and normalized not in adopted_sources:
                adopted_sources.append(normalized)

        workspace_path = str(state.get("workspace_path") or "").strip()
        if workspace_path:
            evidence_dir = Path(workspace_path).expanduser().resolve() / ".evidence"
            if evidence_dir.exists():
                for path in sorted(p for p in evidence_dir.rglob("*") if p.is_file()):
                    relative_path = path.relative_to(Path(workspace_path).expanduser().resolve()).as_posix()
                    if relative_path not in adopted_sources:
                        adopted_sources.append(relative_path)

        ticket_context = cast(dict[str, Any], state.get("intake_ticket_context_summary") or {})
        for key, value in ticket_context.items():
            if str(value).strip():
                source_label = f"ticket:{key}"
                if source_label not in adopted_sources:
                    adopted_sources.append(source_label)

        if not adopted_sources:
            adopted_sources.append("customer issue")
        return adopted_sources

    def _write_shared_memory(self, state: "CaseState", investigation_summary: str) -> None:
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        if not case_id or not workspace_path:
            return
        raw_issue = str(state.get("raw_issue") or "").strip()
        ticket_context = format_ticket_context(cast(dict, state))
        followup_answers = self._format_followup_answers(state)
        intake_category = str(state.get("intake_category") or "ambiguous_case").strip() or "ambiguous_case"
        intake_urgency = str(state.get("intake_urgency") or "medium").strip() or "medium"
        investigation_focus = str(state.get("intake_investigation_focus") or "問い合わせ内容の事実関係を確認する").strip()
        classification_reason = str(state.get("intake_classification_reason") or "").strip()
        escalation_required = self._should_escalate(cast(dict[str, Any], state))
        next_action = (
            NextActionTexts.SAMPLE_PREPARE_ESCALATION
            if escalation_required
            else NextActionTexts.SAMPLE_PREPARE_DRAFT_FOR_APPROVAL
        )
        primary_source = "ticket context" if ticket_context else "customer issue"
        judgment_rationale_parts = [
            "取得済みチケット文脈を優先して状況を整理しました。" if ticket_context else "ユーザー問い合わせを優先して状況を整理しました。",
            "追加確認への回答を反映しました。" if followup_answers else "追加確認への回答は未入力です。",
        ]
        if classification_reason:
            judgment_rationale_parts.append(f"分類理由: {classification_reason}")
        judgment_rationale = " ".join(part for part in judgment_rationale_parts if part)
        context_sections = [section for section in (raw_issue, ticket_context, followup_answers) if section]
        progress_summary = "sample Supervisor が調査結果を再評価し、承認待ちへ進めるかを判断しました。"
        investigation_excerpt = investigation_summary.strip() or "調査結果はこれから整理します。"
        implemented_actions = [
            "問い合わせ内容と既存 shared memory を確認しました。",
            "InvestigateAgent の結果を受け取り、回答ドラフト化の前提を整理しました。",
        ]
        if ticket_context:
            implemented_actions.append("取得済み ticket context を調査判断へ反映しました。")
        if followup_answers:
            implemented_actions.append("顧客の追加回答を確認し、既知情報へ反映しました。")
        confirmed_results = [
            f"調査要約: {investigation_excerpt}",
            f"分類: {intake_category} / 緊急度: {intake_urgency}",
        ]
        requested_range = ""
        range_start = str(state.get("log_extract_range_start") or "").strip()
        range_end = str(state.get("log_extract_range_end") or "").strip()
        incident_timeframe = str(state.get("intake_incident_timeframe") or "").strip()
        adopted_sources = self._collect_adopted_sources(state)
        if range_start and range_end:
            requested_range = f"ログ抽出対象: {range_start} -> {range_end}"
            confirmed_results.append(requested_range)
        supervisor_working_sections = [
            {"title": "Implemented", "bullets": implemented_actions},
            {"title": "Confirmed", "bullets": confirmed_results},
            {"title": "Judgment", "bullets": [judgment_rationale or "n/a"]},
            {"title": "Next Action", "bullets": [next_action]},
        ]
        context_content = {
            "title": "Shared Context",
            "bullets": [
                f"Intake category: {intake_category}",
                f"Intake urgency: {intake_urgency}",
                f"Investigation focus: {investigation_focus}",
                f"Incident timeframe: {incident_timeframe or 'n/a'}",
            ] + ([f"Classification reason: {classification_reason}"] if classification_reason else []),
            "sections": [
                {"title": "Current Issue", "summary": raw_issue},
                {"title": "Ticket Context", "summary": ticket_context},
                {"title": "Customer Follow-up Answers", "summary": followup_answers},
            ],
        }
        progress_content = {
            "title": "Shared Progress",
            "bullets": [
                "Current phase: INVESTIGATING",
                f"Intake category: {intake_category}",
                f"Intake urgency: {intake_urgency}",
                f"Next action: {next_action}",
                f"Ticket context recorded: {'yes' if ticket_context else 'no'}",
            ],
            "sections": [
                {"title": "Latest Supervisor Review", "summary": progress_summary},
                {"title": "Implemented", "bullets": implemented_actions},
                {"title": "Confirmed", "bullets": confirmed_results},
                {"title": "Judgment", "bullets": [judgment_rationale or "n/a"]},
                {"title": "Next Action", "bullets": [next_action]},
            ],
        }
        summary_content = {
            "title": "Shared Summary",
            "summary": investigation_summary.strip(),
            "bullets": [
                f"Conclusion: {investigation_summary.strip() or '調査結果を確認してください。'}",
                f"Judgment rationale: {judgment_rationale}",
                f"Next action: {next_action}",
                f"Primary source: {primary_source}",
                f"Adopted sources: {', '.join(adopted_sources)}",
                f"Intake category: {intake_category}",
                f"Intake urgency: {intake_urgency}",
                f"Incident timeframe: {incident_timeframe or 'n/a'}",
            ],
            "sections": [
                {"title": "Source Context", "summary": "\n\n".join(context_sections)},
            ],
        }
        try:
            self.tool_registry.invoke_tool(
                "write_shared_memory",
                SUPERVISOR_AGENT,
                case_id=case_id,
                workspace_path=workspace_path,
                context_content=context_content,
                progress_content=progress_content,
                summary_content=summary_content,
                mode="replace",
            )
        except Exception:
            return
        try:
            self.tool_registry.invoke_tool(
                "write_working_memory",
                SUPERVISOR_AGENT,
                case_id=case_id,
                workspace_path=workspace_path,
                content={
                    "title": "Supervisor Review",
                    "heading_level": 2,
                    "bullets": [
                        f"Primary source: {primary_source}",
                        f"Investigation summary: {investigation_excerpt}",
                        f"Adopted sources: {', '.join(adopted_sources)}",
                    ] + ([requested_range] if requested_range else []),
                    "sections": supervisor_working_sections,
                },
                mode="append",
            )
        except Exception:
            return

    def execute_investigation(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", StateTransitionHelper.supervisor_investigating(state))

        raw_issue = str(update.get("raw_issue") or "").strip()
        investigation_summary = str(update.get("investigation_summary") or "").strip()
        if not investigation_summary:
            if self.investigate_executor is not None and raw_issue:
                try:
                    case_id = str(update.get("case_id") or "").strip()
                    workspace_path = str(update.get("workspace_path") or "").strip()
                    evidence_log = find_evidence_log_file(workspace_path)
                    attachment_paths = find_attachment_files(workspace_path)
                    update["investigation_evidence_log_path"] = str(evidence_log) if evidence_log is not None else ""
                    update["investigation_attachment_paths"] = [str(path) for path in attachment_paths]
                    investigation_query = self._build_investigation_query(update)
                    instruction_text = InstructionLoader(self.config).load(case_id, SUPERVISOR_AGENT)
                    investigation_result = self.investigate_executor.execute(
                        query=investigation_query,
                        workspace_path=workspace_path or None,
                        instruction_text=instruction_text or None,
                        state=cast(dict[str, Any], update),
                    )
                    investigation_summary = self._extract_investigation_summary(investigation_result)
                except Exception:
                    investigation_summary = self._fallback_investigation_summary(raw_issue)
            else:
                investigation_summary = self._fallback_investigation_summary(raw_issue)

        update["investigation_summary"] = investigation_summary
        self._write_shared_memory(update, investigation_summary)
        update["escalation_required"] = self._should_escalate(cast(dict[str, Any], update))
        if update["escalation_required"]:
            update["escalation_reason"] = str(update.get("escalation_reason") or "追加確認のためバックサポートへ問い合わせます。")
            update["next_action"] = NextActionTexts.SAMPLE_PREPARE_ESCALATION
        else:
            update["escalation_reason"] = ""
            update["next_action"] = NextActionTexts.SAMPLE_PREPARE_DRAFT_FOR_APPROVAL
        return update

    def execute_escalation_review(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", StateTransitionHelper.draft_ready(state))
        if self.back_support_escalation_executor is not None:
            try:
                query = str(update.get("raw_issue") or "").strip() or None
                update.update(cast("CaseState", self.back_support_escalation_executor.execute(query=query)))
            except Exception:
                pass

        update["escalation_required"] = True
        update["escalation_reason"] = str(update.get("escalation_reason") or "追加確認のためバックサポートへ問い合わせます。")
        update["escalation_summary"] = str(
            update.get("escalation_summary")
            or f"サンプルエスカレーション要約: {str(update.get('investigation_summary') or '').strip() or '調査結果を確認してください。'}"
        )
        update["escalation_draft"] = str(
            update.get("escalation_draft")
            or "お世話になっております。追加調査のため、関連ログと再現条件のご確認をお願いいたします。"
        )
        update["draft_response"] = str(update.get("draft_response") or update["escalation_draft"])
        update["next_action"] = NextActionTexts.SAMPLE_ESCALATION_TO_APPROVAL
        return update

    def execute_draft_review(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", StateTransitionHelper.draft_ready(state, current_agent=SUPERVISOR_AGENT))
        update["review_focus"] = "サンプル回答として分かりやすいか確認する"
        update["draft_review_iterations"] = 1
        update["draft_review_max_loops"] = 1
        if not str(update.get("draft_response") or "").strip():
            update["draft_response"] = self._build_draft_response(str(update.get("investigation_summary") or ""))
        update["next_action"] = NextActionTexts.APPROVAL_REVIEW_DRAFT
        return update

    def create_node(self) -> Any:
        from support_ope_agents.models.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("supervisor_entry", lambda state: cast(CaseState, dict(cast(dict[str, Any], state))))
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

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            SUPERVISOR_AGENT,
            "Coordinate sample investigation flow and decide whether escalation is needed",
            kind="supervisor",
        )
