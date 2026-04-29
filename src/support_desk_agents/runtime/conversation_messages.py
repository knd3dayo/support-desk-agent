from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage, message_to_dict, messages_from_dict


SerializedMessage = dict[str, object]


def serialize_langchain_messages(messages: Sequence[BaseMessage]) -> list[SerializedMessage]:
    return [cast(SerializedMessage, message_to_dict(message)) for message in messages]


def deserialize_langchain_messages(messages: Sequence[Mapping[str, object]] | None) -> list[BaseMessage]:
    if not messages:
        return []
    return list(messages_from_dict([dict(message) for message in messages]))


def build_message_from_role(*, role: str, content: str) -> BaseMessage:
    normalized_role = role.strip().lower()
    normalized_content = content.strip()
    if normalized_role in {"user", "human"}:
        return HumanMessage(content=normalized_content)
    if normalized_role in {"assistant", "ai"}:
        return AIMessage(content=normalized_content)
    if normalized_role == "system":
        return SystemMessage(content=normalized_content)
    if normalized_role == "tool":
        return ToolMessage(content=normalized_content, tool_call_id="support-ope-tool")
    return HumanMessage(content=normalized_content)


def coerce_serialized_conversation_messages(messages: Sequence[Mapping[str, object]] | None) -> list[SerializedMessage]:
    if not messages:
        return []

    normalized: list[SerializedMessage] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        message_type = str(message.get("type") or "").strip()
        data = message.get("data")
        if not message_type or not isinstance(data, Mapping):
            continue
        normalized.append(cast(SerializedMessage, dict(message)))

    return normalized


def extract_serialized_messages_from_history(history: Sequence[Mapping[str, object]] | None) -> list[SerializedMessage]:
    if not history:
        return []
    serialized: list[SerializedMessage] = []
    for item in history:
        if not isinstance(item, Mapping):
            continue
        message = item.get("serialized_message")
        if isinstance(message, Mapping):
            serialized.append(cast(SerializedMessage, dict(message)))
    return serialized



def append_serialized_message(
    messages: Sequence[Mapping[str, object]] | None,
    *,
    role: str,
    content: str,
) -> list[SerializedMessage]:
    normalized = coerce_serialized_conversation_messages(messages)
    if content.strip():
        normalized.append(cast(SerializedMessage, message_to_dict(build_message_from_role(role=role, content=content))))
    return normalized


def format_conversation_messages_for_prompt(
    messages: Sequence[Mapping[str, object]] | None,
    *,
    max_messages: int = 8,
) -> str:
    deserialized = deserialize_langchain_messages(messages)
    if not deserialized:
        return ""
    window = deserialized[-max_messages:]
    lines: list[str] = []
    for message in window:
        label = message.type.upper()
        content = str(getattr(message, "text", message.content)).strip()
        if not content:
            continue
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def latest_human_message_text(messages: Sequence[Mapping[str, object]] | None) -> str:
    for message in reversed(deserialize_langchain_messages(messages)):
        if message.type != "human":
            continue
        content = str(getattr(message, "text", message.content)).strip()
        if content:
            return content
    return ""


def extract_message_content(message: object) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(message, Mapping):
        dict_content = message.get("content")
        if isinstance(dict_content, str) and dict_content.strip():
            return dict_content.strip()
    return ""


def extract_result_output_text(result: object) -> str:
    output = getattr(result, "output", None)
    if isinstance(output, str) and output.strip():
        return output.strip()
    if isinstance(result, Mapping):
        dict_output = result.get("output")
        if isinstance(dict_output, str) and dict_output.strip():
            return dict_output.strip()
        dict_messages = result.get("messages")
        if isinstance(dict_messages, Sequence) and not isinstance(dict_messages, (str, bytes)):
            for message in reversed(dict_messages):
                content = extract_message_content(message)
                if content:
                    return content
    attr_messages = getattr(result, "messages", None)
    if isinstance(attr_messages, Sequence) and not isinstance(attr_messages, (str, bytes)):
        for message in reversed(attr_messages):
            content = extract_message_content(message)
            if content:
                return content
    return ""
