from __future__ import annotations

import json
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig


def _get_chat_model(config: AppConfig) -> ChatOpenAI | None:
    if config.llm.provider.lower() != "openai":
        return None
    if not config.llm.api_key:
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


def _fallback_classification(text: str) -> dict[str, str]:
    lowered = text.lower()
    category = "ambiguous_case"
    urgency = "medium"
    investigation_focus = "問い合わせ内容の事実関係と再現条件を確認する"

    if any(token in lowered for token in ["error", "exception", "fail", "failed", "障害", "不具合", "落ちる"]):
        category = "incident_investigation"
        investigation_focus = "エラー条件と影響範囲を切り分ける"
    elif any(token in lowered for token in ["仕様", "spec", "expected", "期待動作"]):
        category = "specification_inquiry"
        investigation_focus = "期待動作と現行仕様の差分を確認する"
    elif any(token in lowered for token in ["どうなる", "どちら", "仕様か不具合", "判定"]):
        category = "ambiguous_case"
        investigation_focus = "仕様解釈と障害切り分けの両面から確認する"

    if any(token in lowered for token in ["urgent", "asap", "至急", "緊急", "critical", "本番"]):
        urgency = "high"

    return {
        "category": category,
        "urgency": urgency,
        "investigation_focus": investigation_focus,
        "reason": "fallback classification",
    }


def build_default_classify_ticket_tool(config: AppConfig):
    async def classify_ticket(text: str, context: str | None = None) -> str:
        normalized_text = str(text or "").strip()
        normalized_context = str(context or "").strip()
        if not normalized_text:
            return json.dumps(_fallback_classification(""), ensure_ascii=False)

        model = _get_chat_model(config)
        if model is None:
            return json.dumps(_fallback_classification(normalized_text), ensure_ascii=False)

        instructions = [
            "You classify a customer support issue for workflow intake.",
            "Return only JSON.",
            "The JSON object must contain category, urgency, investigation_focus, and reason.",
            "Allowed category values: specification_inquiry, incident_investigation, ambiguous_case.",
            "Allowed urgency values: low, medium, high.",
            "Keep investigation_focus and reason concise.",
        ]
        if normalized_context:
            instructions.extend(["", f"Context: {normalized_context}"])
        instructions.extend(["", "Issue:", normalized_text])
        try:
            response = await model.ainvoke([HumanMessage(content="\n".join(instructions))])
        except Exception:
            return json.dumps(_fallback_classification(normalized_text), ensure_ascii=False)
        content = _stringify_response_content(response.content)
        if not content:
            return json.dumps(_fallback_classification(normalized_text), ensure_ascii=False)
        return content

    return classify_ticket