from __future__ import annotations

from collections.abc import Sequence
import inspect
from functools import wraps
from typing import Any, Callable, cast

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.cache.base import BaseCache
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from support_desk_agent.util.asyncio_utils import run_awaitable_sync

try:
    from deepagents.backends import StateBackend
    from deepagents._version import __version__ as DEEPAGENTS_VERSION
    from deepagents.graph import BASE_AGENT_PROMPT
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.memory import MemoryMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from deepagents.middleware.skills import SkillsMiddleware
    from deepagents.middleware.summarization import create_summarization_middleware
except Exception:  # pragma: no cover
    StateBackend = None
    DEEPAGENTS_VERSION = "unknown"
    BASE_AGENT_PROMPT = ""
    FilesystemMiddleware = None
    MemoryMiddleware = None
    PatchToolCallsMiddleware = None
    SkillsMiddleware = None
    create_summarization_middleware = None


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
    model: str | BaseChatModel | None = None,
    memory: list[str] | None = None,
    skills: list[str] | None = None,
    include_todo_list: bool = True,
    include_filesystem: bool = True,
    include_patch_tool_calls: bool = True,
    include_summarization: bool = False,
    summarization_middleware_factory: Callable[[BaseChatModel, Any], AgentMiddleware[Any, Any]] | None = None,
) -> list[AgentMiddleware[Any, Any]]:
    resolved_backend = backend
    if resolved_backend is None and StateBackend is not None:
        resolved_backend = StateBackend()

    configured: list[AgentMiddleware[Any, Any]] = []
    if include_todo_list:
        configured.append(TodoListMiddleware())
    if skills:
        if SkillsMiddleware is None:
            raise RuntimeError("SkillsMiddleware is unavailable")
        if resolved_backend is None:
            raise RuntimeError("A backend is required when skills are enabled")
        configured.append(SkillsMiddleware(backend=resolved_backend, sources=skills))
    if include_filesystem:
        if FilesystemMiddleware is None:
            raise RuntimeError("FilesystemMiddleware is unavailable")
        configured.append(FilesystemMiddleware(backend=resolved_backend))
    if include_summarization:
        if not isinstance(model, BaseChatModel):
            raise RuntimeError("A BaseChatModel instance is required when summarization is enabled")
        if resolved_backend is None:
            raise RuntimeError("A backend is required when summarization is enabled")
        if summarization_middleware_factory is not None:
            configured.append(summarization_middleware_factory(model, resolved_backend))
        else:
            if create_summarization_middleware is None:
                raise RuntimeError("Summarization middleware is unavailable")
            configured.append(create_summarization_middleware(model, resolved_backend))
    if include_patch_tool_calls:
        if PatchToolCallsMiddleware is None:
            raise RuntimeError("PatchToolCallsMiddleware is unavailable")
        configured.append(PatchToolCallsMiddleware())
    if memory:
        if MemoryMiddleware is None:
            raise RuntimeError("MemoryMiddleware is unavailable")
        if resolved_backend is None:
            raise RuntimeError("A backend is required when memory is enabled")
        configured.append(MemoryMiddleware(backend=resolved_backend, sources=memory))
    configured.extend(middleware)
    return configured


def create_deep_agent_compatible_agent(
    model: str | BaseChatModel,
    tools: Sequence[Any] | None = None,
    *,
    backend: Any | None = None,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[Any, Any]] = (),
    memory: list[str] | None = None,
    skills: list[str] | None = None,
    response_format: Any | None = None,
    context_schema: type[Any] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache[Any] | None = None,
    include_todo_list: bool = True,
    include_filesystem: bool = True,
    include_patch_tool_calls: bool = True,
    include_summarization: bool = False,
    summarization_middleware_factory: Callable[[BaseChatModel, Any], AgentMiddleware[Any, Any]] | None = None,
) -> CompiledStateGraph:
    agent = create_agent(
        model,
        tools=tools,
        system_prompt=build_deep_agent_compatible_system_prompt(system_prompt),
        middleware=build_deep_agent_compatible_middleware(
            backend=backend,
            middleware=middleware,
            model=model,
            memory=memory,
            skills=skills,
            include_todo_list=include_todo_list,
            include_filesystem=include_filesystem,
            include_patch_tool_calls=include_patch_tool_calls,
            include_summarization=include_summarization,
            summarization_middleware_factory=summarization_middleware_factory,
        ),
        response_format=response_format,
        context_schema=context_schema,
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
                "ls_integration": "support_desk_agent",
                "versions": {"deepagents": DEEPAGENTS_VERSION},
                "lc_agent_name": name,
            },
        }
    )