from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from support_ope_agents.agents.roles import (
    APPROVAL_AGENT,
    BACK_SUPPORT_ESCALATION_AGENT,
    BACK_SUPPORT_INQUIRY_WRITER_AGENT,
    COMPLIANCE_REVIEWER_AGENT,
    DEFAULT_AGENT_ROLES,
    DRAFT_WRITER_AGENT,
    INTAKE_AGENT,
    KNOWLEDGE_RETRIEVER_AGENT,
    LOG_ANALYZER_AGENT,
    SUPERVISOR_AGENT,
    TICKET_UPDATE_AGENT,
)
from support_ope_agents.config.models import AppConfig, McpToolBinding

from .builtin_tools import build_builtin_tools
from .default_classify_ticket import build_default_classify_ticket_tool
from .default_check_policy import build_default_check_policy_tool
from .default_pii_mask import build_default_pii_mask_tool
from .default_read_shared_memory import build_default_read_shared_memory_tool
from .default_request_revision import build_default_request_revision_tool
from .default_search_documents import build_default_search_documents_tool
from .default_write_draft import build_default_write_draft_tool
from .default_write_shared_memory import build_default_write_shared_memory_tool
from .default_write_working_memory import build_default_write_working_memory_tool
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


def _unavailable_tool(message: str) -> ToolCallable:
    def _handler(*_: object, **__: object) -> str:
        return message

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
        self._validate_logical_tool_settings()

    def get_tools(self, role: str) -> list[ToolSpec]:
        base_tools = [*self._builtin_tools.values(), *self._role_tools.get(role, [])]
        resolved_tools: list[ToolSpec] = []
        for tool in base_tools:
            resolved = self._resolve_tool_configuration(tool)
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
                ToolSpec(
                    "read_shared_memory",
                    "Read shared case memory files",
                    build_default_read_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-reader",
                ),
                ToolSpec("scan_workspace_artifacts", "Scan workspace artifacts", _not_implemented_tool("scan_workspace_artifacts")),
                ToolSpec("spawn_log_analyzer_agent", "Delegate to log analyzer agent", _not_implemented_tool("spawn_log_analyzer_agent")),
                ToolSpec("spawn_knowledge_retriever_agent", "Delegate to knowledge retriever agent", _not_implemented_tool("spawn_knowledge_retriever_agent")),
                ToolSpec("spawn_draft_writer_agent", "Delegate draft creation", _not_implemented_tool("spawn_draft_writer_agent")),
                ToolSpec("spawn_compliance_reviewer_agent", "Delegate compliance review", _not_implemented_tool("spawn_compliance_reviewer_agent")),
                ToolSpec("spawn_back_support_escalation_agent", "Delegate escalation material preparation", _not_implemented_tool("spawn_back_support_escalation_agent")),
                ToolSpec("spawn_back_support_inquiry_writer_agent", "Delegate escalation inquiry drafting", _not_implemented_tool("spawn_back_support_inquiry_writer_agent")),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared context/progress/summary files for a case workspace",
                    build_default_write_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
                ToolSpec(
                    "write_working_memory",
                    "Write agent working memory",
                    build_default_write_working_memory_tool(self._config, INTAKE_AGENT),
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
            ],
            INTAKE_AGENT: [
                ToolSpec(
                    "pii_mask",
                    "Mask API keys and similar secrets from issue text or logs",
                    build_default_pii_mask_tool(self._config),
                    provider="builtin",
                    target="configured-llm-pii-mask",
                ),
                ToolSpec(
                    "external_ticket",
                    "Fetch customer-facing external ticket information",
                    _unavailable_tool(
                        "external_ticket tool is not configured. Configure tools.logical_tools.external_ticket in config.yml."
                    ),
                ),
                ToolSpec(
                    "internal_ticket",
                    "Fetch internal management ticket information",
                    _unavailable_tool(
                        "internal_ticket tool is not configured. Configure tools.logical_tools.internal_ticket in config.yml."
                    ),
                ),
                ToolSpec(
                    "classify_ticket",
                    "Classify customer support ticket with the configured LLM in PoC",
                    build_default_classify_ticket_tool(self._config),
                    provider="builtin",
                    target="configured-llm-classify-ticket",
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared context/progress/summary files for a case workspace",
                    build_default_write_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
            ],
            LOG_ANALYZER_AGENT: [
                ToolSpec("read_log_file", "Read attached log file", _not_implemented_tool("read_log_file")),
                ToolSpec(
                    "detect_log_format",
                    "Detect log format and generate regex-based search results",
                    self._builtin_tools["detect_log_format_and_search"].handler,
                    provider="builtin",
                    target="detect_log_format_and_search",
                ),
                ToolSpec("run_python_analysis", "Run code-based log analysis", _not_implemented_tool("run_python_analysis")),
                ToolSpec(
                    "write_working_memory",
                    "Write agent working memory",
                    build_default_write_working_memory_tool(self._config, LOG_ANALYZER_AGENT),
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
            ],
            KNOWLEDGE_RETRIEVER_AGENT: [
                ToolSpec(
                    "search_documents",
                    "Search configured manuals and knowledge documents via DeepAgents backend",
                    build_default_search_documents_tool(self._config),
                    provider="builtin",
                    target="configured-document-sources",
                ),
                ToolSpec(
                    "external_ticket",
                    "Fetch customer-facing external ticket information",
                    _unavailable_tool(
                        "external_ticket tool is not configured. Configure tools.logical_tools.external_ticket in config.yml."
                    ),
                ),
                ToolSpec(
                    "internal_ticket",
                    "Fetch internal management ticket information",
                    _unavailable_tool(
                        "internal_ticket tool is not configured. Configure tools.logical_tools.internal_ticket in config.yml."
                    ),
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared memory",
                    build_default_write_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
                ToolSpec(
                    "write_working_memory",
                    "Write agent working memory",
                    build_default_write_working_memory_tool(self._config, KNOWLEDGE_RETRIEVER_AGENT),
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
            ],
            DRAFT_WRITER_AGENT: [
                ToolSpec(
                    "write_draft",
                    "Write draft response",
                    build_default_write_draft_tool(self._config, "customer_response_draft"),
                    provider="builtin",
                    target="default-draft-writer",
                ),
            ],
            COMPLIANCE_REVIEWER_AGENT: [
                ToolSpec(
                    "check_policy",
                    "Check draft against configured policies and required notices",
                    build_default_check_policy_tool(self._config),
                    provider="builtin",
                    target="configured-policy-document-sources",
                ),
                ToolSpec(
                    "request_revision",
                    "Summarize revision points for the draft writer",
                    build_default_request_revision_tool(),
                    provider="builtin",
                    target="default-revision-request",
                ),
                ToolSpec(
                    "write_working_memory",
                    "Write agent working memory",
                    build_default_write_working_memory_tool(self._config, COMPLIANCE_REVIEWER_AGENT),
                    provider="builtin",
                    target="default-working-memory-writer",
                ),
            ],
            BACK_SUPPORT_ESCALATION_AGENT: [
                ToolSpec(
                    "read_shared_memory",
                    "Read shared case memory files",
                    build_default_read_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-reader",
                ),
                ToolSpec("scan_workspace_artifacts", "Scan workspace artifacts", _not_implemented_tool("scan_workspace_artifacts")),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared context/progress/summary files for a case workspace",
                    build_default_write_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
            ],
            BACK_SUPPORT_INQUIRY_WRITER_AGENT: [
                ToolSpec(
                    "write_draft",
                    "Write escalation inquiry draft",
                    build_default_write_draft_tool(self._config, "back_support_inquiry_draft"),
                    provider="builtin",
                    target="default-draft-writer",
                ),
                ToolSpec(
                    "write_shared_memory",
                    "Write shared context/progress/summary files for a case workspace",
                    build_default_write_shared_memory_tool(self._config),
                    provider="builtin",
                    target="default-case-memory-writer",
                ),
            ],
            APPROVAL_AGENT: [
                ToolSpec(
                    "record_approval_decision",
                    "Record approval or rejection decisions",
                    _not_implemented_tool("record_approval_decision"),
                ),
            ],
            TICKET_UPDATE_AGENT: [
                ToolSpec(
                    "prepare_ticket_update",
                    "Prepare external ticket update payload",
                    _not_implemented_tool("prepare_ticket_update"),
                ),
                ToolSpec(
                    "zendesk_reply",
                    "Update customer-facing ticket in Zendesk",
                    _not_implemented_tool("zendesk_reply"),
                ),
                ToolSpec(
                    "redmine_update",
                    "Update internal ticket in Redmine",
                    _not_implemented_tool("redmine_update"),
                ),
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

    def _known_logical_tool_names(self) -> set[str]:
        names = set(self._builtin_tools)
        for role in DEFAULT_AGENT_ROLES:
            names.update(self._available_tools_for_role(role))
        return names

    def _validate_logical_tool_settings(self) -> None:
        available_tool_names = self._known_logical_tool_names()
        for logical_tool_name, setting in self._config.tools.logical_tools.items():
            if logical_tool_name not in available_tool_names:
                known_tools = ", ".join(sorted(available_tool_names))
                raise ToolConfigurationError(
                    f"tools.logical_tools.{logical_tool_name} does not match any known logical tool. available_tools=[{known_tools}]"
                )
            if not setting.enabled:
                continue
            if setting.provider == "builtin":
                target_name = setting.builtin_tool or logical_tool_name
                if target_name not in self._builtin_tools and target_name != logical_tool_name:
                    available_builtins = ", ".join(sorted(self._builtin_tools))
                    raise ToolConfigurationError(
                        f"tools.logical_tools.{logical_tool_name} references unknown builtin tool '{target_name}'. "
                        f"available_builtin_tools=[{available_builtins}]"
                    )
                continue
            binding = McpToolBinding(server=str(setting.server), tool=str(setting.tool))
            if self._mcp_override_resolver is None:
                raise ToolConfigurationError(
                    f"tools.logical_tools.{logical_tool_name} requires an MCP resolver, but tools.mcp_manifest_path is not configured"
                )
            self._mcp_override_resolver.validate_logical_tool(logical_tool_name=logical_tool_name, binding=binding)

    def _resolve_tool_configuration(self, tool: ToolSpec) -> ToolSpec | None:
        setting = self._config.tools.get_logical_tool(tool.name)
        if setting is None:
            return tool
        if not setting.enabled:
            return ToolSpec(
                name=tool.name,
                description=tool.description,
                handler=_unavailable_tool(f"Tool '{tool.name}' is disabled in config.yml."),
                provider="disabled",
                target=tool.target,
            )
        if setting.provider == "builtin":
            target_name = setting.builtin_tool or tool.name
            builtin = self._builtin_tools.get(target_name)
            if builtin is None and target_name == tool.name:
                return ToolSpec(
                    name=tool.name,
                    description=tool.description,
                    handler=tool.handler,
                    provider="builtin",
                    target=target_name,
                )
            if builtin is None:
                raise ToolConfigurationError(
                    f"tools.logical_tools.{tool.name} requested builtin provider, but '{target_name}' is not available as a builtin tool"
                )
            return ToolSpec(
                name=tool.name,
                description=tool.description,
                handler=builtin.handler,
                provider="builtin",
                target=target_name,
            )
        if self._mcp_override_resolver is None:
            raise ToolConfigurationError(
                f"tools.logical_tools.{tool.name} requested MCP provider, but no MCP resolver is configured"
            )
        binding = McpToolBinding(server=str(setting.server), tool=str(setting.tool))
        return ToolSpec(
            name=tool.name,
            description=tool.description,
            handler=self._mcp_override_resolver.build_handler(binding, logical_tool_name=tool.name),
            provider=f"mcp:{binding.server}",
            target=binding.tool,
        )