from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from support_desk_agent.runtime.conversation_messages import append_serialized_message
from support_desk_agent.runtime.conversation_messages import coerce_serialized_conversation_messages
from support_desk_agent.runtime.conversation_messages import deserialize_langchain_messages
from support_desk_agent.runtime.conversation_messages import extract_serialized_messages_from_history
from support_desk_agent.runtime.conversation_messages import SerializedMessage


def is_context_dependent_followup(prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", prompt).strip()
    if not normalized or len(normalized) > 40:
        return False
    generic_patterns = (
        "詳細を教えてください",
        "詳しく教えてください",
        "詳しくお願いします",
        "詳細をお願いします",
        "もっと詳しく",
        "詳細は",
    )
    if any(pattern in normalized for pattern in generic_patterns):
        return True
    return normalized in {"詳細", "詳しく", "詳細に", "詳しく教えて", "続きを教えてください"}


def resolve_saved_conversation_messages(
    *,
    state_messages: object,
    history: Sequence[Mapping[str, object]] | None,
) -> list[SerializedMessage]:
    if isinstance(state_messages, list) and state_messages:
        return coerce_serialized_conversation_messages(state_messages)
    return extract_serialized_messages_from_history(history)


def resolve_followup_anchor_from_messages(messages: Sequence[Mapping[str, object]] | None, current_prompt: str) -> str:
    for message in reversed(deserialize_langchain_messages(messages)):
        if message.type != "human":
            continue
        content = str(getattr(message, "text", message.content)).strip()
        if not content:
            continue
        if content == current_prompt and is_context_dependent_followup(content):
            continue
        if is_context_dependent_followup(content):
            continue
        return content
    return ""


def resolve_followup_anchor_issue(
    *,
    history: Sequence[Mapping[str, object]] | None,
    fallback_raw_issue: object,
) -> str:
    for message in reversed(deserialize_langchain_messages(history)):
        if message.type != "human":
            continue
        content = str(getattr(message, "text", message.content)).strip()
        if not content or is_context_dependent_followup(content):
            continue
        return content
    return str(fallback_raw_issue or "").strip()


def build_conversation_messages(
    *,
    prompt: str,
    request_messages: Sequence[Mapping[str, object]] | None,
    saved_messages: Sequence[Mapping[str, object]] | None,
) -> list[SerializedMessage]:
    normalized_request_messages = coerce_serialized_conversation_messages(request_messages)
    if normalized_request_messages:
        return append_serialized_message(normalized_request_messages, role="user", content=prompt)
    return append_serialized_message(saved_messages, role="user", content=prompt)


def resolve_action_prompt(
    *,
    prompt: str,
    request_messages: Sequence[Mapping[str, object]] | None,
    saved_messages: Sequence[Mapping[str, object]] | None,
    fallback_raw_issue: object,
) -> str:
    normalized_prompt = prompt.strip()
    if not is_context_dependent_followup(normalized_prompt):
        return normalized_prompt

    anchor_issue = resolve_followup_anchor_from_messages(request_messages, normalized_prompt)
    if not anchor_issue:
        anchor_issue = resolve_followup_anchor_issue(
            history=saved_messages,
            fallback_raw_issue=fallback_raw_issue,
        )
    if not anchor_issue or anchor_issue == normalized_prompt:
        return normalized_prompt
    return f"{anchor_issue}\n\n[Follow-up request]\n{normalized_prompt}"