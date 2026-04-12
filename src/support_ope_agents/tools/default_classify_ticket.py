from __future__ import annotations

import json
import re
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.conversation_messages import deserialize_langchain_messages


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


def build_default_classify_ticket_tool(config: AppConfig):
    async def classify_ticket(
        text: str,
        context: str | None = None,
        conversation_messages: list[dict[str, object]] | None = None,
    ) -> str:
        normalized_text = str(text or "").strip()
        normalized_context = str(context or "").strip()
        if not normalized_text:
            raise ValueError("classify_ticket requires non-empty text")

        model = _get_chat_model(config)
        instructions = [
            "You classify a customer support issue for workflow intake.",
            "Return only JSON.",
            "The JSON object must contain category, urgency, investigation_focus, and reason.",
            "Allowed category values: specification_inquiry, incident_investigation, ambiguous_case.",
            "Allowed urgency values: low, medium, high.",
            "Keep investigation_focus and reason concise.",
        ]
        prompt_lines: list[str] = []
        if normalized_context:
            prompt_lines.append(f"Context: {normalized_context}")
        prompt_lines.extend(["Issue:", normalized_text])
        response = await model.ainvoke(
            [
                SystemMessage(content="\n".join(instructions)),
                *deserialize_langchain_messages(conversation_messages),
                HumanMessage(content="\n".join(prompt_lines)),
            ]
        )
        content = _stringify_response_content(response.content)
        if not content:
            raise ValueError("classify_ticket returned an empty response")
        return content

    return classify_ticket