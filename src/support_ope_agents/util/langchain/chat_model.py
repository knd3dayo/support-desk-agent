from __future__ import annotations

import inspect
from typing import Any

from langchain_openai import ChatOpenAI

from support_ope_agents.config.models import AppConfig
from support_ope_agents.util.asyncio_utils import run_awaitable_sync


def build_chat_openai_model(config: AppConfig, **kwargs: Any) -> ChatOpenAI:
    if not config.llm.api_key:
        raise ValueError("LLM API key is not configured")

    return ChatOpenAI(
        model=config.llm.model,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        **kwargs,
    )


def close_chat_openai_model(model: Any) -> None:
    for attr_name in ("root_async_client", "root_client"):
        client = getattr(model, attr_name, None)
        close = getattr(client, "close", None)
        if callable(close):
            try:
                result = close()
                if inspect.isawaitable(result):
                    run_awaitable_sync(result)
            except Exception:
                continue