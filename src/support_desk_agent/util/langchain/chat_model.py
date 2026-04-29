from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from support_desk_agent.config.models import AppConfig
def build_chat_openai_model(config: AppConfig, **kwargs: Any) -> ChatOpenAI:
    if not config.llm.api_key:
        raise ValueError("LLM API key is not configured")

    return ChatOpenAI(
        model=config.llm.model,
        # ChatOpenAI.api_key expects SecretStr | Callable[[], str] | Callable[[], Awaitable[str]] | None
        # Pylance complains when passing a plain str, so provide a zero-arg callable that returns the API key.
        api_key=lambda: config.llm.api_key,
        base_url=config.llm.base_url,
        **kwargs,
    )


def close_chat_openai_model(model: Any) -> None:
    del model
    # ChatOpenAI may share underlying client objects with structured wrappers or
    # deferred internal state. In short-lived CLI and agent runs, eager manual
    # close has caused follow-up requests to fail with "client has been closed".
    # Keep the helper as a stable call-site API, but rely on process teardown for
    # client cleanup instead of forcing it here.
    return None