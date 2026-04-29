from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.objective_evaluator import ObjectiveEvaluator
from support_ope_agents.agents.roles import OBJECTIVE_EVALUATOR
from support_ope_agents.agents.roles import INVESTIGATE_AGENT
from support_ope_agents.agents.roles import SUPERVISOR_AGENT
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.util.asyncio_utils import run_awaitable_sync
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.util.formatting import format_result, format_ticket_context
from support_ope_agents.util.workspace_evidence import find_attachment_files, find_evidence_log_file

from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_ope_agents.agents.sample.sample_ticket_update_agent import SampleTicketUpdateAgent
from support_ope_agents.models.state import CaseState
from support_ope_agents.instructions import InstructionLoader


class SampleSupervisorAgent(AbstractAgent):
    PLAN_PASS_SCORE = 80
    RESULT_PASS_SCORE = 80
    MAX_INVESTIGATION_FOLLOWUP_LOOPS = 1

    def __init__(
        self,
        config: Any,
        investigate_executor: "SampleInvestigateAgent | None" = None,
        ticket_update_executor: "SampleTicketUpdateAgent | None" = None,
    ):
        from support_ope_agents.tools.registry import ToolRegistry
        self.config = config
        self.tool_registry = ToolRegistry(config)
        self.investigate_executor = investigate_executor
        self.ticket_update_executor = ticket_update_executor



    @staticmethod
    def _extract_investigation_summary(result: Any) -> str:
        return extract_result_output_text(result) or format_result(result)

    @staticmethod
    def _extract_plan_steps(plan_text: str) -> list[str]:
        bullet_prefixes = ("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ")
        lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
        bullet_lines = [line for line in lines if line.startswith(bullet_prefixes)]
        if bullet_lines:
            return [line.split(" ", 1)[1].strip() if " " in line else line for line in bullet_lines]
        if len(lines) <= 1:
            return lines
        return lines[1:]

    @staticmethod
    def _format_plan_steps(plan_steps: list[str]) -> str:
        if not plan_steps:
            return ""
        return "\n".join(f"- {step}" for step in plan_steps)

    @staticmethod
    def _format_supervisor_followup_notes(notes: list[str]) -> str:
        normalized_notes = [note.strip() for note in notes if note and note.strip()]
        if not normalized_notes:
            return ""
        return "Supervisor followup notes:\n" + "\n".join(f"- {note}" for note in normalized_notes)

    @staticmethod
    def _build_evidence_log_preview(evidence_path: str) -> str:
        normalized_path = evidence_path.strip()
        if not normalized_path:
            return ""
        try:
            lines = Path(normalized_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return ""
        preview_lines = [line.rstrip() for line in lines[:20] if line.strip()]
        if not preview_lines:
            return ""
        return "\n".join(preview_lines)

    @staticmethod
    def _build_review_notes(*, label: str, summary: str, score: int, improvement_points: list[str]) -> list[str]:
        notes = [f"{label} score: {score}"]
        normalized_summary = summary.strip()
        if normalized_summary:
            notes.append(normalized_summary)
        notes.extend(point.strip() for point in improvement_points if point and point.strip())
        return notes

    @staticmethod
    def route_after_investigation(state: dict[str, object]) -> str:
        if state.get("escalation_required"):
            return "escalation_review"
        return "draft_review"

    @staticmethod
    def route_after_approval(state: dict[str, object]) -> str:
        decision = str(state.get("approval_decision", "pending")).lower()
        if decision in {"approved", "approve"}:
            return "ticket_update_subgraph"
        if decision in {"rejected", "reject"}:
            return "draft_review"
        if decision == "reinvestigate":
            return "investigation"
        return "__end__"

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

    def _build_investigation_query(self, state: "CaseState", *, mode: str) -> str:
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
        evidence_preview = self._build_evidence_log_preview(evidence_path)
        evidence_preview_section = (
            "\n".join(
                [
                    "Evidence log preview:",
                    evidence_preview,
                    "上記は Supervisor が存在確認済みの実ファイル内容です。"
                    "このログが存在しない、見つからない、移動されたと断定してはいけません。"
                    "まずこの内容を根拠に分析してください。",
                ]
            )
            if evidence_preview
            else ""
        )
        attachment_paths = [str(path).strip() for path in list(state.get("investigation_attachment_paths") or []) if str(path).strip()]
        attachment_section = (
            "\n".join(
                [
                    "調査可能な添付ファイル path:",
                    *[f"- {path}" for path in attachment_paths],
                    "添付の利用順序: まず path を確認し、ZIP は list_zip_contents で中身を確認して必要な場合だけ extract_zip を使い、PDF は analyze_pdf_files、画像は analyze_image_files を優先してください。",
                ]
            )
            if attachment_paths
            else ""
        )
        plan_summary = str(state.get("plan_summary") or "").strip()
        plan_steps = [str(step).strip() for step in list(state.get("plan_steps") or []) if str(step).strip()]
        plan_section = (
            "\n\n".join(
                part
                for part in (
                    f"確定した調査計画:\n{plan_summary}" if plan_summary else "",
                    f"計画ステップ:\n{self._format_plan_steps(plan_steps)}" if plan_steps else "",
                )
                if part
            )
            if mode == SampleInvestigateAgent.ACTION_MODE
            else ""
        )
        followup_notes_section = (
            self._format_supervisor_followup_notes(list(state.get("supervisor_followup_notes") or []))
            if mode == SampleInvestigateAgent.ACTION_MODE
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
                evidence_preview_section,
                attachment_section,
                plan_section,
                followup_notes_section,
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
        mode_preface = "調査計画だけを作成してください。実際の調査はまだ実行しないでください。" if mode == SampleInvestigateAgent.PLAN_MODE else "確定した調査計画と followup notes を踏まえて調査を実行してください。"
        return "\n\n".join([mode_preface, *parts])

    def _build_objective_evidence(self, state: "CaseState", *, evaluation_target: str) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "evaluation_target": evaluation_target,
            "raw_issue": str(state.get("raw_issue") or "").strip(),
            "plan_summary": str(state.get("plan_summary") or "").strip(),
            "plan_steps": list(state.get("plan_steps") or []),
            "investigation_summary": str(state.get("investigation_summary") or "").strip(),
            "supervisor_followup_notes": list(state.get("supervisor_followup_notes") or []),
            "investigation_evidence_log_path": str(state.get("investigation_evidence_log_path") or "").strip(),
            "investigation_attachment_paths": list(state.get("investigation_attachment_paths") or []),
        }
        return evidence

    def _evaluate_objective(self, state: "CaseState", *, case_id: str, evaluation_target: str) -> Any:
        instruction_text = InstructionLoader(self.config).load(case_id, OBJECTIVE_EVALUATOR)
        evaluator = ObjectiveEvaluator(config=self.config, instruction_text=instruction_text)
        return evaluator.evaluate(
            evidence=self._build_objective_evidence(state, evaluation_target=evaluation_target),
            evaluation_target=cast(Any, evaluation_target),
        )

    def _execute_mode(self, update: "CaseState", *, mode: str, instruction_text: str | None) -> str:
        if self.investigate_executor is None:
            raise RuntimeError("SampleSupervisorAgent requires investigate_executor for the sample workflow.")

        workspace_path = str(update.get("workspace_path") or "").strip()
        investigation_query = self._build_investigation_query(update, mode=mode)
        execute_kwargs: dict[str, Any] = {
            "query": investigation_query,
            "mode": mode,
            "workspace_path": workspace_path or None,
            "instruction_text": instruction_text or None,
            "state": cast(dict[str, Any], update),
        }
        try:
            signature = inspect.signature(self.investigate_executor.execute)
            execute_kwargs = {
                key: value
                for key, value in execute_kwargs.items()
                if key in signature.parameters
            }
        except (TypeError, ValueError):
            pass

        result = self.investigate_executor.execute(**execute_kwargs)
        return self._extract_investigation_summary(result).strip()

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
        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        attachment_ignore_patterns = self.config.data_paths.attachment_ignore_patterns
        evidence_log = find_evidence_log_file(workspace_path, ignore_patterns=attachment_ignore_patterns)
        attachment_paths = find_attachment_files(
            workspace_path,
            ignore_patterns=attachment_ignore_patterns,
        )
        update["investigation_evidence_log_path"] = str(evidence_log) if evidence_log is not None else ""
        update["investigation_attachment_paths"] = [str(path) for path in attachment_paths]

        instruction_text = InstructionLoader(self.config).load(case_id, SUPERVISOR_AGENT)
        plan_summary = self._execute_mode(update, mode=SampleInvestigateAgent.PLAN_MODE, instruction_text=instruction_text)
        update["plan_summary"] = plan_summary
        update["plan_steps"] = self._extract_plan_steps(plan_summary)

        plan_evaluation = self._evaluate_objective(update, case_id=case_id, evaluation_target="plan")
        update["plan_evaluation_summary"] = str(plan_evaluation.overall_summary)
        update["plan_evaluation_score"] = int(plan_evaluation.overall_score)
        update["supervisor_followup_notes"] = self._build_review_notes(
            label="Plan review",
            summary=str(plan_evaluation.overall_summary),
            score=int(plan_evaluation.overall_score),
            improvement_points=list(plan_evaluation.improvement_points),
        )

        followup_loops = int(update.get("investigation_followup_loops") or 0)
        while True:
            update["investigation_followup_loops"] = followup_loops
            investigation_summary = self._execute_mode(update, mode=SampleInvestigateAgent.ACTION_MODE, instruction_text=instruction_text)
            update["investigation_summary"] = investigation_summary
            result_evaluation = self._evaluate_objective(update, case_id=case_id, evaluation_target="result")
            update["investigation_evaluation_summary"] = str(result_evaluation.overall_summary)
            update["investigation_evaluation_score"] = int(result_evaluation.overall_score)
            if int(result_evaluation.overall_score) >= self.RESULT_PASS_SCORE or followup_loops >= self.MAX_INVESTIGATION_FOLLOWUP_LOOPS:
                break
            followup_loops += 1
            update["supervisor_followup_notes"] = self._build_review_notes(
                label="Result review",
                summary=str(result_evaluation.overall_summary),
                score=int(result_evaluation.overall_score),
                improvement_points=list(result_evaluation.improvement_points),
            )

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
        update = cast("CaseState", StateTransitionHelper.draft_ready(state, current_agent=SUPERVISOR_AGENT))
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

    def wait_for_approval(self, state: "CaseState") -> "CaseState":
        return cast(
            "CaseState",
            StateTransitionHelper.waiting_for_approval(state, current_agent=SUPERVISOR_AGENT),
        )

    def create_node(self) -> Any:
        from support_ope_agents.models.state import CaseState

        if self.ticket_update_executor is None:
            raise RuntimeError("SampleSupervisorAgent requires ticket_update_executor for the sample workflow.")

        graph = StateGraph(CaseState)
        graph.add_node("supervisor_entry", lambda state: cast(CaseState, dict(cast(dict[str, Any], state))))
        graph.add_node("investigation", self.execute_investigation)
        graph.add_node("draft_review", self.execute_draft_review)
        graph.add_node("escalation_review", self.execute_escalation_review)
        graph.add_node("wait_for_approval", self.wait_for_approval)
        graph.add_node("ticket_update_subgraph", self.ticket_update_executor.create_node())
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
        graph.add_edge("draft_review", "wait_for_approval")
        graph.add_edge("escalation_review", "wait_for_approval")
        graph.add_conditional_edges(
            "wait_for_approval",
            lambda state: self.route_after_approval(cast(dict[str, object], state)),
            {
                "ticket_update_subgraph": "ticket_update_subgraph",
                "draft_review": "draft_review",
                "investigation": "investigation",
                "__end__": END,
            },
        )
        graph.add_edge("ticket_update_subgraph", END)
        return graph.compile()

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            SUPERVISOR_AGENT,
            "Coordinate sample investigation flow and decide whether escalation is needed",
            kind="supervisor",
        )
