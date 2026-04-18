from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage

from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.langchain import build_chat_openai_model, stringify_response_content


def build_default_pii_mask_tool(config: AppConfig):
    async def pii_mask(text: str, context: str | None = None) -> str:
        normalized_text = str(text or "")
        normalized_context = str(context or "").strip()
        if not normalized_text.strip():
            return normalized_text

        model = build_chat_openai_model(config, temperature=0)
        instructions = [
            "You redact sensitive secrets from customer support text.",
            "Mask API keys, access tokens, bearer tokens, secrets, passwords, private keys, and similar credentials.",
            "Do not summarize.",
            "Preserve the original language and surrounding text as much as possible.",
            "Replace only the sensitive values with [MASKED].",
            "Return only the redacted text.",
        ]
        if normalized_context:
            instructions.extend(["", f"Context: {normalized_context}"])
        instructions.extend(["", "Input text:", normalized_text])
        response = await model.ainvoke([HumanMessage(content="\n".join(instructions))])
        content = stringify_response_content(response.content)
        if not content:
            raise ValueError("pii_mask returned an empty response")
        return content

    return pii_mask