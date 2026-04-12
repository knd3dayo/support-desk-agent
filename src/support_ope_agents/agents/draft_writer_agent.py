from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import DRAFT_WRITER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.tools.document_source_backend import extract_feature_bullets_with_options, extract_relevant_snippet_with_limit


def _get_chat_model(config: AppConfig) -> ChatOpenAI:
    return ChatOpenAI(
        model=config.llm.model,
        api_key=cast(Any, config.llm.api_key),
        base_url=config.llm.base_url,
        temperature=0,
    )


def _stringify_response_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    return str(content).strip()


def _normalize_internal_guidance_lines(revision_request: str) -> set[str]:
    normalized: set[str] = set()
    for line in revision_request.splitlines():
        candidate = line.strip().strip("- ").rstrip("。")
        if candidate:
            normalized.add(candidate)
    return normalized


@dataclass(slots=True)
class DraftWriterPhaseExecutor:
    config: AppConfig
    write_draft_tool: Callable[..., Any]

    @property
    def constraint_mode(self) -> str:
        return self.config.agents.resolve_constraint_mode("DraftWriterAgent")

    def _runtime_constraints_enabled(self) -> bool:
        return self.constraint_mode in {"default", "runtime_only"}

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
    def _resolve_effective_workflow_kind(state: Mapping[str, object]) -> str:
        workflow_kind = str(state.get("workflow_kind") or "").strip()
        intake_category = str(state.get("intake_category") or "").strip()
        valid_values = {"specification_inquiry", "incident_investigation", "ambiguous_case"}
        if workflow_kind not in valid_values:
            return intake_category if intake_category in valid_values else "ambiguous_case"
        if workflow_kind == "ambiguous_case" and intake_category in {"specification_inquiry", "incident_investigation"}:
            return intake_category
        return workflow_kind

    @staticmethod
    def _sanitize_customer_summary(summary: str) -> str:
        sanitized = str(summary or "").strip()
        replacements = {
            "SuperVisorAgent": "今回の調査",
            "KnowledgeRetrieverAgent": "関連資料の確認",
            "LogAnalyzerAgent": "ログ解析",
            "ComplianceReviewerAgent": "レビュー",
            "document_sources": "関連資料",
            "共有メモリ": "調査メモ",
            "ナレッジ照会結果": "関連資料の確認結果",
            "ログ解析結果": "ログ確認結果",
            "Query:": "問い合わせ内容:",
        }
        for source, target in replacements.items():
            sanitized = sanitized.replace(source, target)
        return sanitized

    @staticmethod
    def _format_markdown_links(results: list[dict[str, object]]) -> str:
        links: list[str] = []
        for item in results:
            source_name = str(item.get("source_name") or "").strip()
            matched_paths = item.get("matched_paths")
            if not source_name or not isinstance(matched_paths, list) or not matched_paths:
                continue
            first_path = str(matched_paths[0]).strip()
            if not first_path:
                continue
            links.append(f"[{source_name}]({first_path})")
        deduplicated: list[str] = []
        for link in links:
            if link not in deduplicated:
                deduplicated.append(link)
        return "、".join(deduplicated[:3])

    @staticmethod
    def _is_feature_list_request(state: Mapping[str, object]) -> bool:
        raw_issue = str(state.get("raw_issue") or "").lower()
        if any(token in raw_issue for token in ["機能", "一覧", "できること", "features", "feature"]):
            return True
        detailed_request = any(token in raw_issue for token in ["詳細", "詳しく", "教えて", "まとめて"])
        if not detailed_request:
            return False
        raw_results = state.get("knowledge_retrieval_results")
        if not isinstance(raw_results, list):
            return False
        return any(
            isinstance(item, dict)
            and str(item.get("source_type") or "") == "document_source"
            and (
                bool(list(item.get("feature_bullets") or []))
                or isinstance(item.get("raw_backend"), dict)
            )
            for item in raw_results
        )

    def _raw_backend_content(self, result: Mapping[str, object]) -> str:
        raw_backend = result.get("raw_backend")
        if not isinstance(raw_backend, dict):
            return ""
        file_data = raw_backend.get("file_data")
        if not isinstance(file_data, dict):
            return ""
        return str(file_data.get("content") or "")

    def _feature_bullets_from_result(self, state: Mapping[str, object], result: Mapping[str, object]) -> list[str]:
        raw_feature_bullets = result.get("feature_bullets")
        feature_values = raw_feature_bullets if isinstance(raw_feature_bullets, list) else []
        feature_bullets = [str(item).strip() for item in feature_values if str(item).strip()]
        if feature_bullets:
            return feature_bullets
        raw_content = self._raw_backend_content(result)
        if not raw_content:
            return []
        return extract_feature_bullets_with_options(
            raw_content,
            str(state.get("raw_issue") or ""),
            require_query_match=False,
            heading_keywords=None,
            max_items=5,
        )

    def _summary_from_result(self, state: Mapping[str, object], result: Mapping[str, object]) -> str:
        raw_content = self._raw_backend_content(result)
        if raw_content:
            summary = extract_relevant_snippet_with_limit(raw_content, str(state.get("raw_issue") or ""), 1200)
            return self._sanitize_customer_summary(summary) if self._runtime_constraints_enabled() else summary
        summary = str(result.get("summary") or "").strip()
        return self._sanitize_customer_summary(summary) if self._runtime_constraints_enabled() else summary

    @staticmethod
    def _select_primary_knowledge_result(state: Mapping[str, object]) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
        raw_results = state.get("knowledge_retrieval_results")
        if not isinstance(raw_results, list):
            return None, []
        document_results = [
            item
            for item in raw_results
            if isinstance(item, dict) and str(item.get("source_type") or "") == "document_source"
        ]
        final_source = str(state.get("knowledge_retrieval_final_adopted_source") or "").strip()
        if final_source:
            prioritized = [item for item in document_results if str(item.get("source_name") or "") == final_source]
            if prioritized:
                return prioritized[0], document_results
        return (document_results[0], document_results) if document_results else (None, [])

    def _build_specification_response(self, state: Mapping[str, object]) -> str:
        primary_result, document_results = self._select_primary_knowledge_result(state)
        if primary_result is None:
            return ""

        source_name = str(primary_result.get("source_name") or "対象資料").strip()
        summary = self._summary_from_result(state, primary_result)
        feature_bullets = self._feature_bullets_from_result(state, primary_result)
        is_feature_list_request = self._is_feature_list_request(state)
        links = self._format_markdown_links([primary_result] if feature_bullets and is_feature_list_request else document_results)

        lines = ["お問い合わせありがとうございます。"]
        if summary:
            lines.append(f"結論: {summary}")
        else:
            lines.append(f"結論: {source_name} について、現時点で確認できた内容を整理しました。")

        detail_bullets = feature_bullets[:5]
        if detail_bullets:
            heading = "主な機能:" if is_feature_list_request else "確認できたポイント:"
            lines.append(heading)
            lines.extend(f"- {bullet}" for bullet in detail_bullets)

        if summary and detail_bullets and not is_feature_list_request:
            lines.append("補足: 必要であれば、対象機能ごとの利用方法や関連設定まで掘り下げて確認できます。")
        elif not detail_bullets and summary:
            lines.append("補足: 現時点では概要レベルの確認結果です。必要であれば、利用方法、関連機能、設定観点を追加で整理します。")

        if links:
            lines.append(f"根拠資料: {links}")

        next_action = "次アクション: 必要であれば、個別機能ごとの詳細、利用手順、関連設定の観点で追加調査して案内できます。"
        if is_feature_list_request:
            next_action = "次アクション: 必要であれば、各機能の使い分け、利用手順、制約事項まで分解して案内できます。"
        lines.append(next_action)
        return "\n\n".join(lines)

    def _required_notice_phrase(self) -> str:
        phrases = list(self.config.agents.ComplianceReviewerAgent.notice.required_phrases or [])
        for phrase in phrases:
            normalized = str(phrase).strip().rstrip("。")
            if normalized:
                return normalized + "。"
        return ""

    @staticmethod
    def _extract_exception_names(text: str, limit: int = 3) -> list[str]:
        found: list[str] = []
        for candidate in re.findall(r"\b[\w.$]+(?:Exception|Error)\b", text):
            if candidate not in found:
                found.append(candidate)
            if len(found) >= limit:
                break
        return found

    @staticmethod
    def _extract_representative_line(text: str) -> str:
        match = re.search(r"代表的な(?:異常|例外)行[:：]\s*(.+?)(?:。|$)", text)
        if match:
            return match.group(1).strip()
        return ""

    def _build_support_response_outline(self, state: Mapping[str, object]) -> str:
        investigation_summary = str(state.get("investigation_summary") or "").strip()
        if not investigation_summary:
            return ""

        exception_names = self._extract_exception_names(investigation_summary)
        representative_line = self._extract_representative_line(investigation_summary)
        lowered = investigation_summary.lower()

        conclusion = "結論: ログ上は異常が継続しており、設定または接続条件に起因する例外が発生している可能性があります。"
        if "data source" in lowered and "not found" in lowered:
            conclusion = "結論: ログ上は対象データソースが見つからないことが主要な異常候補です。"

        cause = "原因候補: 詳細な切り分けには追加確認が必要です。"
        if exception_names:
            cause = f"原因候補: {', '.join(exception_names)} が確認されており、設定不整合または接続先構成の問題が疑われます。"
        if "data source" in lowered and "not found" in lowered:
            cause = "原因候補: データソース定義の不足、名称不一致、または起動時に参照可能な設定が不足している可能性があります。"

        next_action = "次アクション: 代表的な異常行の前後ログ、関連設定、直近の変更有無を確認してください。"
        if "data source" in lowered and "not found" in lowered:
            next_action = "次アクション: データソース名、定義の存在有無、接続設定、起動時に読み込まれる構成を優先確認してください。"

        lines = [conclusion, cause]
        if representative_line:
            lines.append(f"確認根拠: {representative_line}")
        lines.append(next_action)
        return "\n".join(lines)

    def _ensure_support_response_structure(self, draft: str, state: Mapping[str, object]) -> str:
        normalized = draft.strip()
        if not normalized:
            return normalized

        workflow_kind = self._resolve_effective_workflow_kind(state)
        if workflow_kind != "incident_investigation":
            return normalized

        required_markers = ["結論", "原因候補", "次アクション"]
        if all(marker in normalized for marker in required_markers):
            return normalized

        outline = self._build_support_response_outline(state)
        if not outline:
            return normalized
        return f"{outline}\n\n{normalized}".strip()

    def _strip_internal_review_content(self, draft: str, revision_request: str) -> str:
        normalized = draft.strip()
        if not normalized:
            return normalized
        if not self._runtime_constraints_enabled():
            return normalized

        hidden_lines = _normalize_internal_guidance_lines(revision_request)
        blocked_fragments = {
            "document_sources の設定と配置を確認してください",
            "確認根拠となるポリシー文書を取得できませんでした",
            "ポリシー文書を取得できませんでした",
            "コンプライアンスレビュー",
            "compliance",
            "以下の観点を反映して文面を見直しました",
        }
        paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
        filtered: list[str] = []
        for paragraph in paragraphs:
            plain = paragraph.strip().rstrip("。")
            if plain in hidden_lines:
                continue
            lowered = plain.lower()
            if any(fragment.lower() in lowered for fragment in blocked_fragments):
                continue
            filtered.append(paragraph)
        return self._sanitize_customer_summary("\n\n".join(filtered))

    async def _generate_with_llm(self, state: dict[str, object]) -> str:
        model = _get_chat_model(self.config)
        prompt = {
            "task": "Write a support-agent-facing investigation response draft in Japanese.",
            "investigation_summary": str(state.get("investigation_summary") or ""),
            "review_focus": str(state.get("review_focus") or ""),
            "revision_request": str(state.get("compliance_revision_request") or ""),
            "knowledge_source": str(state.get("knowledge_retrieval_final_adopted_source") or ""),
            "constraints": (
                [
                    "Avoid overconfident claims.",
                    "Do not promise unconfirmed remediation.",
                    "Keep the response practical for support agents.",
                ]
                if self._runtime_constraints_enabled()
                else []
            ),
            "internal_revision_guidance": str(state.get("compliance_revision_request") or ""),
        }
        response = await model.ainvoke(
            [HumanMessage(content="Return only the final draft text.\n" + json.dumps(prompt, ensure_ascii=False))]
        )
        content = _stringify_response_content(response.content)
        if not content:
            raise ValueError("draft_writer returned an empty response")
        sanitized = self._strip_internal_review_content(content, str(state.get("compliance_revision_request") or ""))
        sanitized = self._ensure_support_response_structure(sanitized, state)
        if not sanitized:
            raise ValueError("draft_writer returned an empty sanitized response")
        return sanitized

    def execute(self, state: dict[str, object]) -> dict[str, object]:
        existing_draft = str(state.get("draft_response") or "").strip()
        revision_request = str(state.get("compliance_revision_request") or "")
        if existing_draft and not revision_request:
            draft_response = self._strip_internal_review_content(existing_draft, revision_request)
            draft_response = self._ensure_support_response_structure(draft_response, state)
        else:
            generated = ""
            if self._resolve_effective_workflow_kind(state) == "specification_inquiry" and not revision_request:
                generated = self._build_specification_response(state)
            if not generated:
                generated = self._invoke_tool(self._generate_with_llm, state)
            draft_response = self._strip_internal_review_content(generated, revision_request)
            draft_response = self._ensure_support_response_structure(draft_response, state)
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        if case_id and workspace_path:
            self._invoke_tool(self.write_draft_tool, case_id, workspace_path, draft_response, "replace")
        return {"draft_response": draft_response}


def build_draft_writer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        DRAFT_WRITER_AGENT,
        "Write support-facing draft response",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )