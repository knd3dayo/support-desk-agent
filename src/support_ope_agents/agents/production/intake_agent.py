from __future__ import annotations

import base64
import inspect
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.runtime.case_titles import derive_case_title
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.util.shared_memory_payload import SharedMemoryDocumentPayload

# IntakeAgentはケースの初期受け入れと分類を担当するエージェントで、
# 問い合わせ内容のPIIマスキング、チケット情報の取得、分類と緊急度判定、品質ゲートによる検証、
# 状態の最終化などの機能を提供します。
if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class IntakeAgent:
    """
    サポート担当者からの問い合わせ内容を受け取り、初期分類や緊急度判定を行うエージェント。
    create_node() で Intake フェーズの実装をLanggraph のノードとして提供します。
    IntakeAgentは以下のSubGraphノードで構成されます:
    prepare_state() でケース状態の初期化、
    apply_pii_mask() で問い合わせ内容の PII マスキング、
    classify_issue() で問い合わせ内容の分類と緊急度判定、
    quality_gate() で分類結果の検証と不足情報の抽出、
    finalize_state() で最終的な状態更新と共有コンテキストへの記録を行う。
    """
    @dataclass(frozen=True, slots=True)
    class ValidationResult:
        category: str
        urgency: str
        incident_timeframe: str
        missing_fields: list[str]
        rework_reason: str

    config: AppConfig
    pii_mask_tool: Callable[..., Any]
    external_ticket_tool: Callable[..., Any]
    internal_ticket_tool: Callable[..., Any]
    classify_ticket_tool: Callable[..., Any]
    write_shared_memory_tool: Callable[..., Any]
    write_working_memory_tool: Callable[..., Any] | None = None
    runtime_harness_manager: RuntimeHarnessManager | None = None

    def _invoke_tool(self, tool: Callable[..., Any], *args: object, **kwargs: object) -> str:
        try:
            result = tool(*args, **kwargs)
        except TypeError:
            if kwargs:
                try:
                    signature = inspect.signature(tool)
                    filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
                    result = tool(*args, **filtered_kwargs)
                except (TypeError, ValueError):
                    result = tool(*args)
            else:
                result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(cast(Any, result))
            return str(resolved)
        return str(result)

    @staticmethod
    def _parse_classification(raw_result: str) -> dict[str, str]:
        normalized_raw_result = raw_result.strip()
        try:
            parsed = json.loads(normalized_raw_result)
        except json.JSONDecodeError:
            code_fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", normalized_raw_result, flags=re.DOTALL)
            inline_json_match = re.search(r"(\{.*\})", normalized_raw_result, flags=re.DOTALL)
            candidate = ""
            if code_fence_match:
                candidate = code_fence_match.group(1).strip()
            elif inline_json_match:
                candidate = inline_json_match.group(1).strip()
            if candidate:
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    return {"category": "ambiguous_case", "urgency": "medium", "investigation_focus": normalized_raw_result}
            else:
                return {"category": "ambiguous_case", "urgency": "medium", "investigation_focus": normalized_raw_result}

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

    @staticmethod
    def _normalize_incident_urgency(raw_issue: str, category: str, urgency: str) -> str:
        normalized_category = category.strip()
        normalized_urgency = urgency.strip() or "medium"
        if normalized_category != "incident_investigation":
            return normalized_urgency

        lowered = raw_issue.lower()
        high_markers = ["urgent", "critical", "至急", "緊急", "本番", "業務停止", "sev1", "sev2", "ダウン"]
        if any(marker in lowered for marker in high_markers):
            return "high"

        evidence_markers = ["error", "exception", "timeout", "fail", ".log", "ログ", "エラー", "障害"]
        if any(marker in lowered for marker in evidence_markers):
            return normalized_urgency if normalized_urgency in {"medium", "high"} else "medium"

        return normalized_urgency

    def _resolve_classification_urgency(self, raw_issue: str, category: str, urgency: str) -> str:
        constraint_mode = (
            self.runtime_harness_manager.resolve(INTAKE_AGENT)
            if self.runtime_harness_manager is not None
            else self.config.agents.resolve_constraint_mode(INTAKE_AGENT)
        )
        if not RuntimeHarnessManager.runtime_constraints_enabled_for_mode(constraint_mode):
            # Runtime constraint: urgency normalization is skipped when intake runtime constraints are off.
            return urgency.strip() or "medium"
        return self._normalize_incident_urgency(raw_issue, category, urgency)

    @staticmethod
    def resolve_intake_category(state: CaseState, memory_snapshot: dict[str, str]) -> str:
        state_category = str(state.get("intake_category") or "").strip()
        if state_category:
            return state_category

        combined = "\n".join(memory_snapshot.values())
        match = re.search(r"(?:Category|Intake category):\s*([^\n]+)", combined)
        if match:
            return match.group(1).strip()
        return "ambiguous_case"

    @staticmethod
    def resolve_intake_urgency(state: CaseState, memory_snapshot: dict[str, str]) -> str:
        state_urgency = str(state.get("intake_urgency") or "").strip()
        if state_urgency:
            return state_urgency

        combined = "\n".join(memory_snapshot.values())
        match = re.search(r"(?:Urgency|Intake urgency):\s*([^\n]+)", combined)
        if match:
            return match.group(1).strip()
        return "medium"

    @staticmethod
    def resolve_incident_timeframe(state: CaseState, memory_snapshot: dict[str, str]) -> str:
        timeframe = str(state.get("intake_incident_timeframe") or "").strip()
        if timeframe:
            return timeframe

        combined = "\n".join(memory_snapshot.values())
        match = re.search(r"Incident timeframe:\s*([^\n]+)", combined)
        if match:
            return match.group(1).strip()
        return ""

    @classmethod
    def resolve_effective_workflow_kind(cls, state: CaseState, memory_snapshot: dict[str, str]) -> str:
        workflow_kind = str(state.get("workflow_kind") or "").strip()
        intake_category = cls.resolve_intake_category(state, memory_snapshot)
        valid_values = {"specification_inquiry", "incident_investigation", "ambiguous_case"}

        if workflow_kind not in valid_values:
            return intake_category if intake_category in valid_values else "ambiguous_case"

        if workflow_kind == "ambiguous_case" and intake_category in {"specification_inquiry", "incident_investigation"}:
            return intake_category

        return workflow_kind

    @classmethod
    def validate_intake(cls, state: CaseState, memory_snapshot: dict[str, str]) -> ValidationResult:
        missing_fields: list[str] = []
        category = cls.resolve_intake_category(state, memory_snapshot)
        urgency = cls.resolve_intake_urgency(state, memory_snapshot)
        incident_timeframe = cls.resolve_incident_timeframe(state, memory_snapshot)
        evidence_files = cls._resolve_evidence_files(state)

        if not category:
            missing_fields.append("intake_category")
        if not urgency:
            missing_fields.append("intake_urgency")
        if category == "incident_investigation" and not incident_timeframe and not evidence_files:
            missing_fields.append("intake_incident_timeframe")

        rework_reason = ""
        if missing_fields:
            reasons = {
                "intake_category": "問い合わせ分類が未確定",
                "intake_urgency": "緊急度が未設定",
                "intake_incident_timeframe": "障害発生時間帯が未確認",
            }
            rework_reason = "、".join(reasons[field_name] for field_name in missing_fields)

        return cls.ValidationResult(
            category=category,
            urgency=urgency,
            incident_timeframe=incident_timeframe,
            missing_fields=missing_fields,
            rework_reason=rework_reason,
        )

    @staticmethod
    def _resolve_evidence_files(state: CaseState) -> list[str]:
        evidence = state.get("intake_evidence_files")
        if isinstance(evidence, Iterable) and not isinstance(evidence, (str, bytes, dict)):
            normalized = [str(item).strip() for item in evidence if str(item).strip()]
            if normalized:
                return normalized

        workspace_path = str(state.get("workspace_path") or "").strip()
        if not workspace_path:
            return []

        evidence_dirs = (".evidence", "evidence")
        root = Path(workspace_path).expanduser().resolve()
        collected: list[str] = []
        for subdir_name in evidence_dirs:
            target_dir = root / subdir_name
            if not target_dir.exists() or not target_dir.is_dir():
                continue
            for path in sorted(child for child in target_dir.rglob("*") if child.is_file()):
                try:
                    collected.append(path.relative_to(root).as_posix())
                except ValueError:
                    collected.append(str(path))
        return collected

    @staticmethod
    def _ticket_lookup_requested(update: dict[str, object], ticket_kind: str) -> bool:
        return bool(update.get(f"{ticket_kind}_ticket_lookup_enabled"))

    def _ticket_tool_is_enabled(self, ticket_kind: str) -> bool:
        settings = self.config.tools.get_logical_tool(f"{ticket_kind}_ticket")
        return not (settings is not None and not settings.enabled)

    @staticmethod
    def _is_ticket_tool_unavailable_error(error: Exception) -> bool:
        message = str(error)
        unavailable_markers = (
            "tool is not configured",
            "is disabled in config.yml",
            "requested MCP provider",
            "requires an MCP resolver",
        )
        return any(marker in message for marker in unavailable_markers)

    @staticmethod
    def _build_ticket_summary(parsed: dict[str, object], raw_result: str) -> str:
        for key in ("summary", "message", "title", "subject", "description"):
            value = str(parsed.get(key) or "").strip()
            if value:
                return value
        payload = {key: value for key, value in parsed.items() if key != "attachments"}
        if payload:
            return json.dumps(payload, ensure_ascii=False)
        return raw_result

    @staticmethod
    def _attachment_filename(item: dict[str, object], fallback_prefix: str, index: int) -> str:
        candidate = str(item.get("filename") or item.get("file_name") or item.get("name") or "").strip()
        if candidate:
            return candidate
        extension = str(item.get("extension") or ".txt").strip()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        return f"{fallback_prefix}-{index}{extension or '.txt'}"

    def _materialize_ticket_attachment(self, attachment_dir: Path, ticket_kind: str, index: int, item: object) -> str | None:
        if isinstance(item, str):
            path = attachment_dir / f"{ticket_kind}-attachment-{index}.txt"
            path.write_text(item, encoding="utf-8")
            return str(path)
        if not isinstance(item, dict):
            return None

        filename = self._attachment_filename(item, f"{ticket_kind}-attachment", index)
        path = attachment_dir / filename
        base64_data = str(item.get("content_base64") or item.get("base64") or "").strip()
        if base64_data:
            path.write_bytes(base64.b64decode(base64_data))
            return str(path)

        text_content = item.get("content")
        if isinstance(text_content, str):
            path.write_text(text_content, encoding="utf-8")
            return str(path)

        source_path = str(item.get("path") or "").strip()
        if source_path:
            return source_path

        path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def _hydrate_ticket_context(
        self,
        *,
        ticket_kind: str,
        ticket_id: str,
        tool: Callable[..., Any],
        workspace_path: str,
    ) -> tuple[str, list[str]]:
        intake_dir = (Path(workspace_path).expanduser().resolve() / self.config.data_paths.artifacts_subdir / "intake")
        intake_dir.mkdir(parents=True, exist_ok=True)

        raw_result = self._invoke_tool(tool, ticket_id=ticket_id)
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            parsed = None

        artifact_paths: list[str] = []
        if isinstance(parsed, dict):
            response_path = intake_dir / f"{ticket_kind}_ticket.json"
            response_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            artifact_paths.append(str(response_path))
            attachments = parsed.get("attachments")
            if isinstance(attachments, list) and attachments:
                attachment_dir = intake_dir / f"{ticket_kind}_attachments"
                attachment_dir.mkdir(parents=True, exist_ok=True)
                for index, item in enumerate(attachments, start=1):
                    materialized = self._materialize_ticket_attachment(attachment_dir, ticket_kind, index, item)
                    if materialized:
                        artifact_paths.append(materialized)
            return self._build_ticket_summary(parsed, raw_result), artifact_paths

        response_path = intake_dir / f"{ticket_kind}_ticket.txt"
        response_path.write_text(raw_result, encoding="utf-8")
        artifact_paths.append(str(response_path))
        return raw_result, artifact_paths

    def prepare_state(self, state: CaseState) -> CaseState:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        update["status"] = "TRIAGED"
        update["current_agent"] = INTAKE_AGENT
        update.setdefault("intake_ticket_context_summary", {})
        update.setdefault("intake_ticket_artifacts", {})
        update.setdefault("customer_followup_answers", {})
        update["masked_issue"] = raw_issue
        if raw_issue and not str(update.get("case_title") or "").strip():
            update["case_title"] = derive_case_title(raw_issue, fallback=str(update.get("case_id") or "新規ケース"))
        return cast("CaseState", update)

    PII_MASK_PROMPT = "Mask API keys, tokens, and secrets for intake processing."

    def apply_pii_mask(self, state: CaseState) -> CaseState:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        if raw_issue and self.config.agents.IntakeAgent.pii_mask.enabled:
            update["masked_issue"] = self._invoke_tool(
                self.pii_mask_tool,
                raw_issue,
                self.PII_MASK_PROMPT,
            )
        return cast("CaseState", update)

    def hydrate_tickets(self, state: CaseState) -> CaseState:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        if not raw_issue or not workspace_path:
            return cast("CaseState", update)

        ticket_summaries = cast(dict[str, str], update.get("intake_ticket_context_summary") or {})
        ticket_artifacts = cast(dict[str, list[str]], update.get("intake_ticket_artifacts") or {})
        for ticket_kind, tool in (("external", self.external_ticket_tool), ("internal", self.internal_ticket_tool)):
            ticket_id = str(update.get(f"{ticket_kind}_ticket_id") or "").strip()
            if not ticket_id or not self._ticket_lookup_requested(update, ticket_kind):
                continue

            if not self._ticket_tool_is_enabled(ticket_kind):
                update[f"{ticket_kind}_ticket_lookup_enabled"] = False
                continue

            try:
                summary, artifact_paths = self._hydrate_ticket_context(
                    ticket_kind=ticket_kind,
                    ticket_id=ticket_id,
                    tool=tool,
                    workspace_path=workspace_path,
                )
            except Exception as error:
                if not self._is_ticket_tool_unavailable_error(error):
                    raise
                update[f"{ticket_kind}_ticket_lookup_enabled"] = False
                continue
            ticket_summaries[f"{ticket_kind}_ticket"] = summary
            ticket_artifacts[f"{ticket_kind}_ticket"] = artifact_paths

        update["intake_ticket_context_summary"] = ticket_summaries
        update["intake_ticket_artifacts"] = ticket_artifacts
        return cast("CaseState", update)

    CLASSIFY_PROMPT = "Classify the intake issue for customer support workflow routing and investigation planning."

    def classify_issue(self, state: CaseState) -> CaseState:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        masked_issue = str(update.get("masked_issue") or raw_issue)
        if not raw_issue:
            return cast("CaseState", update)

        classification = self._parse_classification(
            self._invoke_tool(
                self.classify_ticket_tool,
                masked_issue,
                self.CLASSIFY_PROMPT,
                conversation_messages=cast(list[dict[str, object]], update.get("conversation_messages") or []),
            )
        )
        update["intake_category"] = classification["category"]
        update["intake_urgency"] = self._resolve_classification_urgency(
            masked_issue,
            classification["category"],
            classification["urgency"],
        )
        update["intake_investigation_focus"] = classification["investigation_focus"]
        update["intake_classification_reason"] = classification.get("reason", "")
        extracted_timeframe = self._extract_incident_timeframe(masked_issue)
        existing_timeframe = str(update.get("intake_incident_timeframe") or "").strip()
        update["intake_incident_timeframe"] = extracted_timeframe or existing_timeframe
        return cast("CaseState", update)

    def quality_gate(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["intake_evidence_files"] = self._resolve_evidence_files(cast("CaseState", update))
        validation_result = self.validate_intake(
            cast("CaseState", update),
            {"context": "", "progress": "", "summary": ""},
        )
        update["intake_category"] = validation_result.category
        update["intake_urgency"] = validation_result.urgency
        if validation_result.incident_timeframe:
            update["intake_incident_timeframe"] = validation_result.incident_timeframe
        update["intake_missing_fields"] = validation_result.missing_fields
        update["intake_rework_reason"] = validation_result.rework_reason
        update["intake_rework_required"] = bool(validation_result.missing_fields)
        return cast("CaseState", update)

    def finalize_state(self, state: CaseState) -> CaseState:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        masked_issue = str(update.get("masked_issue") or raw_issue)
        classification = {
            "category": str(update.get("intake_category") or "ambiguous_case"),
            "urgency": str(update.get("intake_urgency") or "medium"),
            "investigation_focus": str(update.get("intake_investigation_focus") or "問い合わせ内容の事実関係を確認する"),
            "reason": str(update.get("intake_classification_reason") or ""),
        }
        incident_timeframe = str(update.get("intake_incident_timeframe") or "")

        missing_fields = cast(list[str], update.get("intake_missing_fields") or [])
        followup_questions: dict[str, str] = {}
        if update.get("intake_rework_required") and missing_fields:
            followup_questions = self._build_followup_questions(missing_fields)
            update["status"] = "WAITING_CUSTOMER_INPUT"
            update["intake_followup_questions"] = followup_questions
            update["next_action"] = "不足情報をユーザーへ確認し、追加入力後に Intake を再実行する"
        else:
            update["intake_followup_questions"] = {}

        workspace_path = str(update.get("workspace_path") or "").strip()
        case_id = str(update.get("case_id") or "").strip()
        if workspace_path and case_id:
            if self.write_working_memory_tool is not None and raw_issue:
                working_payload: SharedMemoryDocumentPayload = {
                    "title": "Intake Result",
                    "heading_level": 2,
                    "bullets": [
                        f"Raw issue: {raw_issue}",
                        f"Masked issue: {masked_issue}",
                        f"Category: {classification['category']}",
                        f"Urgency: {classification['urgency']}",
                        f"Investigation focus: {classification['investigation_focus']}",
                        f"Reason: {classification['reason'] or 'n/a'}",
                        f"Incident timeframe: {incident_timeframe or 'n/a'}",
                        f"Evidence files: {', '.join(cast(list[str], update.get('intake_evidence_files') or [])) or 'n/a'}",
                        f"Follow-up required: {'yes' if bool(followup_questions) else 'no'}",
                    ],
                }
                if missing_fields:
                    working_payload["bullets"].append(f"Missing fields: {', '.join(missing_fields)}")
                if followup_questions:
                    working_payload["sections"] = [
                        {
                            "title": "Follow-up Questions",
                            "bullets": [f"{field_name}: {question}" for field_name, question in followup_questions.items()],
                        }
                    ]
                self._invoke_tool(
                    self.write_working_memory_tool, case_id, workspace_path, working_payload, 
                    "append")

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
                evidence_files = cast(list[str], update.get("intake_evidence_files") or [])
                if evidence_files:
                    context_payload["sections"][0]["bullets"].append(f"Evidence files: {', '.join(evidence_files)}")
                if incident_timeframe:
                    context_payload["sections"][0]["bullets"].append(f"Incident timeframe: {incident_timeframe}")
                if classification.get("reason"):
                    context_payload["sections"][0]["bullets"].append(f"Reason: {classification['reason']}")
                ticket_summaries = cast(dict[str, str], update.get("intake_ticket_context_summary") or {})
                ticket_artifacts = cast(dict[str, list[str]], update.get("intake_ticket_artifacts") or {})
                if ticket_summaries:
                    context_payload["sections"].append(
                        {
                            "title": "Ticket Context",
                            "bullets": [f"{name}: {summary}" for name, summary in ticket_summaries.items()]
                            + [f"{name} artifacts: {', '.join(paths)}" for name, paths in ticket_artifacts.items() if paths],
                        }
                    )
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
                        context_payload["sections"].append({"title": "Customer Follow-up Answers", "bullets": answer_bullets})
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
            if update.get("intake_ticket_artifacts"):
                progress_payload["bullets"].append("Ticket hydration: completed")
            if update.get("execution_mode") == "plan":
                if followup_questions:
                    progress_payload["bullets"].append("Planning note: plan モードだが、不足情報の確認が先に必要")
                else:
                    progress_payload["bullets"].append("Planning note: plan モードのため、次はユーザー承認待ちの案内を行う")
            self._invoke_tool(
                self.write_shared_memory_tool, case_id, workspace_path, 
                context_payload, progress_payload)

        if followup_questions:
            return cast("CaseState", update)

        update["intake_rework_required"] = False
        update["intake_rework_reason"] = ""
        update["intake_missing_fields"] = []
        update["intake_followup_questions"] = {}

        if update.get("execution_mode") == "plan":
            update["next_action"] = "ユーザーに計画を提示して承認を得る"
        elif update.get("customer_followup_answers"):
            update["next_action"] = "追加情報を踏まえて SuperVisorAgent が再評価する"
        else:
            update["next_action"] = "SuperVisorAgent が調査フェーズを開始する"
        return cast("CaseState", update)

    def execute(self, state: CaseState) -> CaseState:
        update = self.prepare_state(state)
        update = self.apply_pii_mask(update)
        update = self.hydrate_tickets(update)
        update = self.classify_issue(update)
        update = self.quality_gate(update)
        return self.finalize_state(update)

    def wait_for_customer_input(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "WAITING_CUSTOMER_INPUT"
        update["current_agent"] = INTAKE_AGENT
        if not update.get("next_action"):
            update["next_action"] = "IntakeAgent の質問に回答し、追加情報を提供してください。"
        return cast("CaseState", update)

    def create_node(self):
        from support_ope_agents.workflow.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("intake_prepare", lambda state: cast(CaseState, self.prepare_state(cast(CaseState, state))))
        graph.add_node("intake_mask", lambda state: cast(CaseState, self.apply_pii_mask(cast(CaseState, state))))
        graph.add_node("intake_hydrate_tickets", lambda state: cast(CaseState, self.hydrate_tickets(cast(CaseState, state))))
        graph.add_node("intake_classify", lambda state: cast(CaseState, self.classify_issue(cast(CaseState, state))))
        graph.add_node("intake_quality_gate", lambda state: cast(CaseState, self.quality_gate(cast(CaseState, state))))
        graph.add_node("intake_finalize", lambda state: cast(CaseState, self.finalize_state(cast(CaseState, state))))
        graph.add_edge(START, "intake_prepare")
        graph.add_edge("intake_prepare", "intake_mask")
        graph.add_edge("intake_mask", "intake_hydrate_tickets")
        graph.add_edge("intake_hydrate_tickets", "intake_classify")
        graph.add_edge("intake_classify", "intake_quality_gate")
        graph.add_edge("intake_quality_gate", "intake_finalize")
        graph.add_edge("intake_finalize", END)
        return graph.compile()

    def create_wait_node(self):
        from support_ope_agents.workflow.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("wait_for_customer_input", self.wait_for_customer_input)
        graph.add_edge(START, "wait_for_customer_input")
        graph.add_edge("wait_for_customer_input", END)
        return graph.compile()

    @staticmethod
    def build_intake_agent_definition() -> AgentDefinition:
        return AgentDefinition(INTAKE_AGENT, "Triage and initialize the case", kind="phase", parent_role=SUPERVISOR_AGENT)