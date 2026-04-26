from __future__ import annotations

from collections.abc import Sequence
import inspect
from functools import wraps
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.cache.base import BaseCache
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from support_ope_agents.util.asyncio_utils import run_awaitable_sync

try:
    from deepagents._version import __version__ as DEEPAGENTS_VERSION
    from deepagents.graph import BASE_AGENT_PROMPT
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
except Exception:  # pragma: no cover
    DEEPAGENTS_VERSION = "unknown"
    BASE_AGENT_PROMPT = ""
    FilesystemMiddleware = None
    PatchToolCallsMiddleware = None


def build_deep_agent_compatible_system_prompt(system_prompt: str | SystemMessage | None) -> str | SystemMessage | None:
    if not BASE_AGENT_PROMPT:
        return system_prompt
    if system_prompt is None:
        return BASE_AGENT_PROMPT
    if isinstance(system_prompt, SystemMessage):
        return SystemMessage(
            content_blocks=[
                *system_prompt.content_blocks,
                {"type": "text", "text": f"\n\n{BASE_AGENT_PROMPT}"},
            ]
        )
    return f"{system_prompt}\n\n{BASE_AGENT_PROMPT}"


def wrap_tool_handler_sync(handler: Any) -> Any:
    if not callable(handler):
        return handler

    @wraps(handler)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        result = handler(*args, **kwargs)
        if inspect.isawaitable(result):
            return run_awaitable_sync(cast(Any, result))
        return result

    return _wrapped


def build_deep_agent_compatible_middleware(
    *,
    backend: Any | None = None,
    middleware: Sequence[AgentMiddleware[Any, Any]] = (),
    include_todo_list: bool = True,
    include_filesystem: bool = True,
    include_patch_tool_calls: bool = True,
) -> list[AgentMiddleware[Any, Any]]:
    configured: list[AgentMiddleware[Any, Any]] = []
    if include_todo_list:
        configured.append(TodoListMiddleware())
    if include_filesystem:
        if FilesystemMiddleware is None:
            raise RuntimeError("FilesystemMiddleware is unavailable")
        configured.append(FilesystemMiddleware(backend=backend))
    if include_patch_tool_calls:
        if PatchToolCallsMiddleware is None:
            raise RuntimeError("PatchToolCallsMiddleware is unavailable")
        configured.append(PatchToolCallsMiddleware())
    configured.extend(middleware)
    return configured


def create_deep_agent_compatible_agent(
    model: str | BaseChatModel,
    tools: Sequence[Any] | None = None,
    *,
    backend: Any | None = None,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[Any, Any]] = (),
    response_format: Any | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache[Any] | None = None,
    include_todo_list: bool = True,
    include_filesystem: bool = True,
    include_patch_tool_calls: bool = True,
) -> CompiledStateGraph:
    agent = create_agent(
        model,
        tools=tools,
        system_prompt=build_deep_agent_compatible_system_prompt(system_prompt),
        middleware=build_deep_agent_compatible_middleware(
            backend=backend,
            middleware=middleware,
            include_todo_list=include_todo_list,
            include_filesystem=include_filesystem,
            include_patch_tool_calls=include_patch_tool_calls,
        ),
        response_format=response_format,
        checkpointer=checkpointer,
        store=store,
        debug=debug,
        name=name,
        cache=cache,
    )
    return agent.with_config(
        {
            "recursion_limit": 9_999,
            "metadata": {
                "ls_integration": "support_ope_agents",
                "versions": {"deepagents": DEEPAGENTS_VERSION},
                "lc_agent_name": name,
            },
        }
    )