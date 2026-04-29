from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from support_desk_agent.memory import CaseMemoryStore
from support_desk_agent.runtime.case_id_resolver import CaseIdResolverService
from support_desk_agent.runtime.case_titles import derive_case_title
from support_desk_agent.runtime.conversation_messages import append_serialized_message
from support_desk_agent.models.state import CaseState


def has_explicit_ticket_id(value: str | None) -> bool:
    return bool(value and value.strip())


def resolve_ticket_lookup_enabled(
    *,
    explicit_ticket_id: str | None,
    saved_ticket_id: object,
    saved_lookup_enabled: object,
    ticket_kind: str,
    case_id_resolver_service: CaseIdResolverService,
) -> bool:
    if has_explicit_ticket_id(explicit_ticket_id):
        return True
    if isinstance(saved_lookup_enabled, bool):
        return saved_lookup_enabled

    return bool(str(saved_ticket_id or "").strip())


def persist_case_title(
    *,
    memory_store: CaseMemoryStore,
    case_id: str,
    workspace_path: str,
    case_title: str | None,
) -> str:
    normalized = str(case_title or "").strip() or case_id
    memory_store.update_case_metadata(workspace_path, case_id=case_id, case_title=normalized)
    return normalized


def sync_case_title_from_state(
    *,
    memory_store: CaseMemoryStore,
    case_id: str,
    workspace_path: str,
    state: CaseState,
    prompt: str,
) -> str:
    existing_title = str(memory_store.read_case_metadata(workspace_path).get("case_title") or "").strip()
    if existing_title:
        return existing_title
    case_title = str(state.get("case_title") or "").strip() or derive_case_title(prompt, fallback=case_id)
    return persist_case_title(
        memory_store=memory_store,
        case_id=case_id,
        workspace_path=workspace_path,
        case_title=case_title,
    )


def backfill_case_title(
    *,
    memory_store: CaseMemoryStore,
    case_id: str,
    workspace_path: str,
    history: list[dict[str, object]],
) -> str:
    for message in history:
        if str(message.get("role") or "") != "user":
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        return persist_case_title(
            memory_store=memory_store,
            case_id=case_id,
            workspace_path=workspace_path,
            case_title=derive_case_title(content, fallback=case_id),
        )
    return persist_case_title(
        memory_store=memory_store,
        case_id=case_id,
        workspace_path=workspace_path,
        case_title=case_id,
    )


def append_chat_message(
    *,
    memory_store: CaseMemoryStore,
    case_id: str,
    workspace_path: str,
    role: str,
    content: str,
    trace_id: str | None,
    event: str,
) -> None:
    normalized = content.strip()
    if not normalized:
        return
    memory_store.append_chat_history(
        case_id,
        workspace_path,
        {
            "role": role,
            "content": normalized,
            "serialized_message": append_serialized_message([], role=role, content=normalized)[0],
            "trace_id": trace_id,
            "event": event,
            "created_at": datetime.now(tz=UTC).isoformat(),
        },
    )


def build_assistant_history_content(result: dict[str, object]) -> str:
    state = cast(dict[str, object], result.get("state") or {})
    candidates = [
        str(state.get("customer_response_draft") or "").strip(),
        str(state.get("draft_response") or "").strip(),
        str(state.get("next_action") or "").strip(),
        str(result.get("plan_summary") or "").strip(),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    status = str(state.get("status") or "").strip()
    return f"Workflow status: {status}" if status else "Workflow completed."


def normalize_state_ids(state: dict[str, object] | CaseState, *, trace_id: str | None = None) -> CaseState:
    normalized_trace_id = normalize_trace_id(
        str(trace_id or state.get("trace_id") or state.get("session_id") or new_trace_id())
    )
    normalized_state = cast(CaseState, dict(state))
    normalized_state.pop("session_id", None)
    normalized_state["trace_id"] = normalized_trace_id
    normalized_state["thread_id"] = normalized_trace_id
    normalized_state["workflow_run_id"] = normalized_trace_id
    return normalized_state


def normalize_trace_id(value: str) -> str:
    if value.startswith("SESSION-"):
        return f"TRACE-{value.removeprefix('SESSION-')}"
    if value.startswith("TRACE-"):
        return value
    return f"TRACE-{value}"


def new_trace_id() -> str:
    return f"TRACE-{uuid4().hex}"