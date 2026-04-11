from __future__ import annotations

import re
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig


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


def build_default_pii_mask_tool(config: AppConfig):
    async def pii_mask(text: str, context: str | None = None) -> str:
        normalized_text = str(text or "")
        normalized_context = str(context or "").strip()
        if not normalized_text.strip():
            return normalized_text

        model = _get_chat_model(config)
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
        content = _stringify_response_content(response.content)
        if not content:
            raise ValueError("pii_mask returned an empty response")
        return content

    return pii_mask