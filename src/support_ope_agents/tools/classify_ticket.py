from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime.conversation_messages import deserialize_langchain_messages
from support_ope_agents.util.langchain import build_chat_openai_model, stringify_response_content
from support_ope_agents.instructions import InstructionLoader


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

        # instructionsの外部化: InstructionLoader経由で取得
        try:
            loader = InstructionLoader(config, memory_store=None, runtime_harness_manager=None)  # memory_storeは不要なためNone
            instructions = loader.load(case_id="classify_ticket", role="classify_ticket")
            if not instructions:
                raise Exception()
        except Exception:
            # フォールバック: 旧デフォルト
            instructions = """You classify a customer support issue for workflow intake.\nReturn only JSON.\nThe JSON object must contain category, urgency, investigation_focus, and reason.\nAllowed category values: specification_inquiry, incident_investigation, ambiguous_case.\nAllowed urgency values: low, medium, high.\nKeep investigation_focus and reason concise."""

        prompt_lines: list[str] = []
        if normalized_context:
            prompt_lines.append(f"Context: {normalized_context}")
        prompt_lines.extend(["Issue:", normalized_text])
        response = await model.ainvoke(
            [
                SystemMessage(content=instructions),
                *deserialize_langchain_messages(conversation_messages),
                HumanMessage(content="\n".join(prompt_lines)),
            ]
        )
        content = stringify_response_content(response.content)
        if not content:
            raise ValueError("classify_ticket returned an empty response")
        return content

    return classify_ticket