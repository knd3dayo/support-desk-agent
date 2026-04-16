from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig


def build_chat_openai_model(config: AppConfig, **kwargs: Any) -> ChatOpenAI:
    if not config.llm.api_key:
        raise ValueError("LLM API key is not configured")

    return ChatOpenAI(
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        **kwargs,
    )