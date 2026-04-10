from __future__ import annotations

import re
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig


def _get_chat_model(config: AppConfig) -> ChatOpenAI | None:
    if config.llm.provider.lower() != "openai":
        return None
    if not config.llm.api_key:
        return None
    return ChatOpenAI(model=config.llm.model, api_key=cast(Any, config.llm.api_key), temperature=0)


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


def _fallback_mask(text: str) -> str:
    masked = text
    substitutions = [
        (
            re.compile(r"(?i)\b(api[_ -]?key|token|secret|password|passwd|authorization)\b\s*[:=]\s*([^\s,;]+)"),
            lambda match: f"{match.group(1)}=[MASKED]",
        ),
        (
            re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
            lambda _: "sk-[MASKED]",
        ),
        (
            re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b"),
            lambda _: "gh_[MASKED]",
        ),
        (
            re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
            lambda _: "AKIA[MASKED]",
        ),
        (
            re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]{12,}"),
            lambda _: "Bearer [MASKED]",
        ),
    ]
    for pattern, replacement in substitutions:
        masked = pattern.sub(replacement, masked)
    return masked


def build_default_pii_mask_tool(config: AppConfig):
    async def pii_mask(text: str, context: str | None = None) -> str:
        normalized_text = str(text or "")
        normalized_context = str(context or "").strip()
        if not normalized_text.strip():
            return normalized_text

        model = _get_chat_model(config)
        if model is None:
            return _fallback_mask(normalized_text)

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
        return content or _fallback_mask(normalized_text)

    return pii_mask