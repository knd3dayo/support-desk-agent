from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.conversation_messages import deserialize_langchain_messages
from support_ope_agents.util.langchain import build_chat_openai_model, stringify_response_content


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

        model = build_chat_openai_model(config, temperature=0)
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
        content = stringify_response_content(response.content)
        if not content:
            raise ValueError("classify_ticket returned an empty response")
        return content

    return classify_ticket