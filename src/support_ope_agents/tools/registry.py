from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from support_ope_agents.agents.roles import (
    COMPLIANCE_REVIEWER_AGENT,
    DEFAULT_AGENT_ROLES,
    DRAFT_WRITER_AGENT,
    INTAKE_AGENT,
    KNOWLEDGE_RETRIEVER_AGENT,
    LOG_ANALYZER_AGENT,
    SUPERVISOR_AGENT,
)
from support_ope_agents.config.models import AppConfig, BuiltinToolBinding, DisabledToolBinding, McpToolBinding

from .builtin_tools import build_builtin_tools
from .mcp_overrides import McpToolOverrideResolver, ToolConfigurationError


ToolCallable = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolCallable
    provider: str = "local"
    target: str | None = None


def _not_implemented_tool(name: str) -> ToolCallable:
    def _handler(*_: object, **__: object) -> str:
        return f"Tool '{name}' is not implemented yet."

    return _handler


class ToolRegistry:
    def __init__(self, config: AppConfig, mcp_override_resolver: McpToolOverrideResolver | None = None):
        self._config = config
        self._mcp_override_resolver = mcp_override_resolver
        self._builtin_tools = {
            name: ToolSpec(
                name=builtin.name,
                description=builtin.description,
                handler=builtin.handler,
                provider="builtin",
                target=builtin.name,
            )
            for name, builtin in build_builtin_tools(config).items()
        }
        self._role_tools = self._build_role_tools()
        self._normalized_overrides = self._normalize_overrides()
        self._validate_overrides()

    def get_tools(self, role: str) -> list[ToolSpec]:
        base_tools = [*self._builtin_tools.values(), *self._role_tools.get(role, [])]
        resolved_tools: list[ToolSpec] = []
        for tool in base_tools:
            resolved = self._resolve_tool_override(role, tool)
            if resolved is not None:
                resolved_tools.append(resolved)
        return resolved_tools

    def list_roles(self) -> Iterable[str]:
        return DEFAULT_AGENT_ROLES

    def _build_role_tools(self) -> dict[str, list[ToolSpec]]:
        return {
            SUPERVISOR_AGENT: [
                ToolSpec("inspect_workflow_state", "Inspect case workflow state", _not_implemented_tool("inspect_workflow_state")),
                ToolSpec("evaluate_agent_result", "Evaluate a child agent result", _not_implemented_tool("evaluate_agent_result")),
                ToolSpec("route_phase_agent", "Select next phase agent", _not_implemented_tool("route_phase_agent")),
                ToolSpec("read_shared_memory", "Read shared case memory", _not_implemented_tool("read_shared_memory")),
                ToolSpec("scan_workspace_artifacts", "Scan workspace artifacts", _not_implemented_tool("scan_workspace_artifacts")),
                ToolSpec("spawn_log_analyzer_agent", "Delegate to log analyzer agent", _not_implemented_tool("spawn_log_analyzer_agent")),
                ToolSpec("spawn_knowledge_retriever_agent", "Delegate to knowledge retriever agent", _not_implemented_tool("spawn_knowledge_retriever_agent")),
                ToolSpec("spawn_draft_writer_agent", "Delegate draft creation", _not_implemented_tool("spawn_draft_writer_agent")),
                ToolSpec("spawn_compliance_reviewer_agent", "Delegate compliance review", _not_implemented_tool("spawn_compliance_reviewer_agent")),
            ],
            INTAKE_AGENT: [
                ToolSpec("pii_mask", "Mask PII from issue text or logs", _not_implemented_tool("pii_mask")),
                ToolSpec("classify_ticket", "Classify customer support ticket", _not_implemented_tool("classify_ticket")),
                ToolSpec("write_shared_memory", "Update shared memory files", _not_implemented_tool("write_shared_memory")),
            ],
            LOG_ANALYZER_AGENT: [
                ToolSpec("read_log_file", "Read attached log file", _not_implemented_tool("read_log_file")),
                ToolSpec("run_python_analysis", "Run code-based log analysis", _not_implemented_tool("run_python_analysis")),
                ToolSpec("write_working_memory", "Write agent working memory", _not_implemented_tool("write_working_memory")),
            ],
            KNOWLEDGE_RETRIEVER_AGENT: [
                ToolSpec("search_kb", "Search knowledge base", _not_implemented_tool("search_kb")),
                ToolSpec("search_ticket_history", "Search historical tickets", _not_implemented_tool("search_ticket_history")),
                ToolSpec("write_working_memory", "Write agent working memory", _not_implemented_tool("write_working_memory")),
            ],
            DRAFT_WRITER_AGENT: [
                ToolSpec("write_draft", "Write draft response", _not_implemented_tool("write_draft")),
            ],
            COMPLIANCE_REVIEWER_AGENT: [
                ToolSpec("check_policy", "Check compliance policy", _not_implemented_tool("check_policy")),
                ToolSpec("request_revision", "Request draft revision", _not_implemented_tool("request_revision")),
            ],
        }

    def _available_tools_for_role(self, role: str) -> dict[str, ToolSpec]:
        combined = [*self._builtin_tools.values(), *self._role_tools.get(role, [])]
        available: dict[str, ToolSpec] = {}
        for tool in combined:
            if tool.name in available:
                raise ToolConfigurationError(f"Duplicate logical tool '{tool.name}' is defined for role '{role}'")
            available[tool.name] = tool
        return available

    def _normalize_overrides(self) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for role, overrides in self._config.tools.overrides.items():
            role_overrides = normalized.setdefault(role, {})
            for logical_tool_name, binding in overrides.items():
                if logical_tool_name in role_overrides:
                    raise ToolConfigurationError(
                        f"tools.overrides defines duplicate logical tool '{logical_tool_name}' for role '{role}'"
                    )
                role_overrides[logical_tool_name] = binding
        return normalized

    def _validate_overrides(self) -> None:
        if not self._config.tools.has_overrides():
            return

        for normalized_role, overrides in self._normalized_overrides.items():
            if normalized_role not in self._role_tools:
                available_roles = ", ".join(DEFAULT_AGENT_ROLES)
                raise ToolConfigurationError(
                    f"tools.overrides references unknown role '{normalized_role}'. Available roles=[{available_roles}]"
                )

            available_tools = self._available_tools_for_role(normalized_role)
            available_tool_names = set(available_tools)
            for logical_tool_name, binding in overrides.items():
                if logical_tool_name not in available_tool_names:
                    known_tools = ", ".join(sorted(available_tool_names))
                    raise ToolConfigurationError(
                        f"tools.overrides.{normalized_role}.{logical_tool_name} does not match any logical tool for role '{normalized_role}'. "
                        f"available_tools=[{known_tools}]"
                    )
                if isinstance(binding, BuiltinToolBinding):
                    target_name = binding.tool or logical_tool_name
                    if target_name not in self._builtin_tools:
                        available_builtins = ", ".join(sorted(self._builtin_tools))
                        raise ToolConfigurationError(
                            f"tools.overrides.{normalized_role}.{logical_tool_name} references unknown builtin tool '{target_name}'. "
                            f"available_builtin_tools=[{available_builtins}]"
                        )
                    continue
                if isinstance(binding, DisabledToolBinding):
                    continue
                if binding.type == "mcp":
                    if self._mcp_override_resolver is None:
                        raise ToolConfigurationError(
                            "tools.mcp_manifest_path is required when configuring tools.overrides with MCP bindings"
                        )
                    self._mcp_override_resolver.validate_binding(
                        role=normalized_role,
                        logical_tool_name=logical_tool_name,
                        binding=binding,
                    )

    def _resolve_tool_override(self, role: str, tool: ToolSpec) -> ToolSpec | None:
        overrides = self._normalized_overrides.get(role, {})
        binding = overrides.get(tool.name)
        if binding is None:
            return tool

        if isinstance(binding, DisabledToolBinding):
            return None

        if isinstance(binding, BuiltinToolBinding):
            target_name = binding.tool or tool.name
            builtin = self._builtin_tools[target_name]
            return ToolSpec(
                name=tool.name,
                description=tool.description,
                handler=builtin.handler,
                provider="builtin",
                target=target_name,
            )

        if isinstance(binding, McpToolBinding):
            if self._mcp_override_resolver is None:
                raise ToolConfigurationError(
                    f"tools.overrides.{role}.{tool.name} requested an MCP binding but no MCP resolver is configured"
                )
            return ToolSpec(
                name=tool.name,
                description=tool.description,
                handler=self._mcp_override_resolver.build_handler(binding, logical_tool_name=tool.name),
                provider=f"mcp:{binding.server}",
                target=binding.tool,
            )

        return tool