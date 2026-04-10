from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Callable, cast

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import DRAFT_WRITER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import AppConfig


def _get_chat_model(config: AppConfig) -> ChatOpenAI | None:
    if config.llm.provider.lower() != "openai":
        return None
    if not config.llm.api_key:
        return None
    if str(config.llm.api_key).strip().lower() in {"dummy", "test", "placeholder"}:
        return None
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


def _format_notice_text(notice_phrase: str) -> str:
    normalized = notice_phrase.strip().rstrip("。")
    if not normalized:
        return ""
    return f"【注意事項】{normalized}。"


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

    def _fallback_draft(self, state: dict[str, object]) -> str:
        notice_settings = self.config.agents.ComplianceReviewerAgent.notice
        notice_text = ""
        if notice_settings.required and notice_settings.required_phrases:
            notice_text = _format_notice_text(str(notice_settings.required_phrases[0]))

        investigation_summary = str(state.get("investigation_summary") or "調査結果を整理中です。").strip()
        review_focus = str(state.get("review_focus") or "").strip()
        revision_request = str(state.get("compliance_revision_request") or "").strip()
        source_hint = str(state.get("knowledge_retrieval_final_adopted_source") or "").strip()

        lines: list[str] = []
        lines.append("お問い合わせありがとうございます。")
        lines.append(f"現時点の確認結果では、{investigation_summary}")
        if source_hint:
            lines.append(f"関連情報は {source_hint} を根拠候補として確認しています。")
        if review_focus:
            lines.append(f"今回の回答では、{review_focus} を重視して表現を調整しています。")
        lines.append("追加で確認が必要な点があれば、確認結果が揃い次第ご案内します。")
        if notice_text:
            lines.append(notice_text)
        return "\n\n".join(line for line in lines if line.strip())

    def _strip_internal_review_content(self, draft: str, revision_request: str) -> str:
        normalized = draft.strip()
        if not normalized:
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
        return "\n\n".join(filtered)

    def _normalize_notice_placement(self, draft: str) -> str:
        normalized = draft.strip()
        if not normalized:
            return normalized

        notice_settings = self.config.agents.ComplianceReviewerAgent.notice
        if not notice_settings.required or not notice_settings.required_phrases:
            return normalized

        formatted_notice = _format_notice_text(str(notice_settings.required_phrases[0]))
        if not formatted_notice:
            return normalized

        paragraphs = [paragraph.strip() for paragraph in normalized.split("\n\n") if paragraph.strip()]
        raw_notices = {str(phrase).strip().rstrip("。") for phrase in notice_settings.required_phrases if str(phrase).strip()}
        raw_notices.add(formatted_notice.strip().rstrip("。"))
        filtered: list[str] = []
        for paragraph in paragraphs:
            candidate = paragraph.strip().removeprefix("【注意事項】").strip().rstrip("。")
            if candidate in raw_notices:
                continue
            filtered.append(paragraph)
        filtered.append(formatted_notice)
        return "\n\n".join(filtered)

    async def _generate_with_llm(self, state: dict[str, object]) -> str:
        model = _get_chat_model(self.config)
        if model is None:
            return self._fallback_draft(state)

        notice_settings = self.config.agents.ComplianceReviewerAgent.notice
        prompt = {
            "task": "Write a customer-facing support response draft in Japanese.",
            "investigation_summary": str(state.get("investigation_summary") or ""),
            "review_focus": str(state.get("review_focus") or ""),
            "revision_request": str(state.get("compliance_revision_request") or ""),
            "knowledge_source": str(state.get("knowledge_retrieval_final_adopted_source") or ""),
            "constraints": [
                "Avoid overconfident claims.",
                "Do not promise unconfirmed remediation.",
                "Keep the response customer-friendly.",
                "Do not mention internal compliance review comments, policy retrieval failures, or document_sources configuration to the customer.",
            ],
            "required_notice": notice_settings.required,
            "required_notice_phrases": list(notice_settings.required_phrases),
            "internal_revision_guidance": str(state.get("compliance_revision_request") or ""),
        }
        try:
            response = await model.ainvoke(
                [HumanMessage(content="Return only the final draft text.\n" + json.dumps(prompt, ensure_ascii=False))]
            )
            content = _stringify_response_content(response.content)
            sanitized = self._strip_internal_review_content(content or self._fallback_draft(state), str(state.get("compliance_revision_request") or ""))
            return self._normalize_notice_placement(sanitized or self._fallback_draft(state))
        except Exception:
            return self._fallback_draft(state)

    def execute(self, state: dict[str, object]) -> dict[str, object]:
        generated = self._invoke_tool(self._generate_with_llm, state)
        sanitized = self._strip_internal_review_content(generated, str(state.get("compliance_revision_request") or ""))
        draft_response = self._normalize_notice_placement(sanitized)
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        if case_id and workspace_path:
            self._invoke_tool(self.write_draft_tool, case_id, workspace_path, draft_response, "replace")
        return {"draft_response": draft_response}


def build_draft_writer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        DRAFT_WRITER_AGENT,
        "Write customer-facing draft response",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )