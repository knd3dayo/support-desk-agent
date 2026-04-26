from __future__ import annotations

from importlib.resources import files
from pathlib import Path
import re
from typing import Any, Protocol, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_ope_agents.tools.registry import ToolRegistry
from support_ope_agents.workflow.production.case_workflow import CaseWorkflow as ProductionCaseWorkflow
from support_ope_agents.models.state import CaseState
from support_ope_agents.models.state_transitions import CaseStatuses


class _ReadablePath(Protocol):
    def exists(self) -> bool: ...
    def read_text(self, encoding: str = "utf-8") -> str: ...


def build_control_catalog(
    *,
    config: AppConfig,
    tool_registry: ToolRegistry,
    agent_definitions: list[AgentDefinition],
    runtime_harness_manager: RuntimeHarnessManager | None = None,
) -> dict[str, object]:
    harness = runtime_harness_manager or RuntimeHarnessManager(config)
    workflow_nodes, workflow_edges = _workflow_catalog()

    instructions = _build_instruction_catalog(config, agent_definitions)
    agents = [_build_agent_entry(config, tool_registry, definition, instructions) for definition in agent_definitions]
    logical_tools = _build_logical_tool_catalog(config)
    control_points = _build_control_points(config, instructions)

    return {
        "summary": {
            "agent_count": len(agents),
            "workflow_node_count": len(workflow_nodes),
            "workflow_edge_count": len(workflow_edges),
            "logical_tool_count": len(logical_tools),
            "instruction_role_count": len(_instruction_role_entries(instructions)),
            "control_point_count": len(control_points),
        },
        "workflow": {
            "settings": {
                "approval_node": config.workflow.approval_node,
                "auto_compress": config.workflow.auto_compress,
                "max_context_chars": config.workflow.max_context_chars,
                "compress_threshold_chars": config.workflow.compress_threshold_chars,
                "max_summary_chars": config.workflow.max_summary_chars,
            },
            "nodes": workflow_nodes,
            "edges": workflow_edges,
        },
        "instructions": instructions,
        "logical_tools": logical_tools,
        "agents": agents,
        "control_points": control_points,
        "runtime_constraints": harness.describe_roles([definition.role for definition in agent_definitions]),
        "runtime_policies": harness.build_policy_snapshot([definition.role for definition in agent_definitions]),
    }


def build_runtime_audit(
    *,
    case_id: str,
    state: CaseState,
    config: AppConfig,
    instruction_loader: InstructionLoader,
    runtime_harness_manager: RuntimeHarnessManager | None = None,
) -> dict[str, object]:
    harness = runtime_harness_manager or RuntimeHarnessManager(config)
    workflow_path = list(ProductionCaseWorkflow().reconstruct_main_workflow_path(state))
    workflow_kind = _effective_workflow_kind(state)
    used_roles = _resolve_used_roles(workflow_path, workflow_kind)
    common_instruction_constraints = _infer_instruction_constraints(_load_common_instruction_text(config))
    instruction_resolution = [
        _build_instruction_resolution_entry(
            config,
            instruction_loader,
            case_id,
            role,
            common_instruction_constraints,
            runtime_harness_manager=harness,
        )
        for role in used_roles
    ]
    runtime_constraints = harness.describe_roles(used_roles)
    runtime_policies = harness.build_policy_snapshot(used_roles)
    runtime_policy_effects = harness.evaluate_policy_impacts(used_roles, state)
    decision_log = _build_runtime_decision_log(state, workflow_path, config)

    return {
        "summary": {
            "case_id": case_id,
            "trace_id": str(state.get("trace_id") or ""),
            "status": str(state.get("status") or "unknown"),
            "runtime_mode": "production",
            "execution_mode": str(state.get("execution_mode") or ""),
            "workflow_kind": workflow_kind,
            "result": _result_label(state),
            "approval_route": _approval_route(state),
            "used_role_count": len(used_roles),
            "decision_count": len(decision_log),
            "draft_review_iterations": _coerce_int(state.get("draft_review_iterations"), default=0),
        },
        "workflow_path": workflow_path,
        "used_roles": used_roles,
        "common_instruction_constraints": common_instruction_constraints,
        "instruction_resolution": instruction_resolution,
        "runtime_constraints": runtime_constraints,
        "runtime_policies": runtime_policies,
        "runtime_policy_effects": runtime_policy_effects,
        "decision_log": decision_log,
        "active_control_point_ids": [
            str(item.get("control_point_id") or "")
            for item in decision_log
            if str(item.get("control_point_id") or "")
        ],
    }


def _build_instruction_resolution_entry(
    config: AppConfig,
    instruction_loader: InstructionLoader,
    case_id: str,
    role: str,
    common_instruction_constraints: list[str],
    runtime_harness_manager: RuntimeHarnessManager | None = None,
) -> dict[str, object]:
    harness = runtime_harness_manager or RuntimeHarnessManager(config)
    # Runtime constraint: expose the resolved mode and enabled capabilities in the control catalog.
    constraint_mode = harness.resolve(role)
    instruction_text = instruction_loader.load(case_id, role, constraint_mode=constraint_mode)
    inferred_constraints = [
        constraint for constraint in _infer_instruction_constraints(instruction_text) if constraint not in common_instruction_constraints
    ]
    return {
        "role": role,
        "resolved_sources": _resolve_instruction_sources(config, role, constraint_mode=constraint_mode),
        "instruction_excerpt": _instruction_excerpt(instruction_text),
        "inferred_constraints": inferred_constraints,
        "constraint_mode": constraint_mode,
        "instruction_enabled": harness.should_load_instructions(role),
        "runtime_enabled": harness.should_apply_runtime_constraints(role),
        "summary_constraints_enabled": harness.should_use_summary_constraints(role),
    }


def _load_common_instruction_text(config: AppConfig) -> str:
    default_root = files("support_ope_agents.instructions.defaults")
    parts: list[str] = []

    default_common = default_root / "common.md"
    if _path_exists(default_common):
        parts.append(default_common.read_text(encoding="utf-8").strip())

    override_root = config.config_paths.instructions_path
    if override_root is not None:
        common_override = override_root / "common.md"
        if common_override.exists():
            parts.append(common_override.read_text(encoding="utf-8").strip())

    return "\n\n".join(part for part in parts if part)


def _build_instruction_catalog(config: AppConfig, agent_definitions: list[AgentDefinition]) -> dict[str, object]:
    default_root = files("support_ope_agents.instructions.defaults")
    override_root = config.config_paths.instructions_path
    common_default = default_root / "common.md"
    common_override = override_root / "common.md" if override_root is not None else None

    return {
        "default_root": str(default_root),
        "override_root": str(override_root) if override_root is not None else None,
        "common": {
            "default_path": str(common_default),
            "default_exists": _path_exists(common_default),
            "override_path": str(common_override) if common_override is not None else None,
            "override_exists": common_override.exists() if common_override is not None else False,
        },
        "roles": [_build_instruction_role_entry(default_root, override_root, definition.role) for definition in agent_definitions],
    }


def _build_instruction_role_entry(default_root: Any, override_root: Path | None, role: str) -> dict[str, object]:
    default_path = default_root / f"{role}.md"
    override_path = override_root / f"{role}.md" if override_root is not None else None
    sources = []
    if _path_exists(default_root.joinpath("common.md")):
        sources.append(str(default_root / "common.md"))
    if _path_exists(default_path):
        sources.append(str(default_path))
    if override_root is not None:
        common_override = override_root / "common.md"
        if common_override.exists():
            sources.append(str(common_override))
        if override_path is not None and override_path.exists():
            sources.append(str(override_path))
    return {
        "role": role,
        "default_path": str(default_path),
        "default_exists": _path_exists(default_path),
        "override_path": str(override_path) if override_path is not None else None,
        "override_exists": override_path.exists() if override_path is not None else False,
        "resolved_sources": sources,
    }


def _build_logical_tool_catalog(config: AppConfig) -> list[dict[str, object]]:
    logical_tools: list[dict[str, object]] = []
    for name in sorted(config.tools.logical_tools):
        settings = config.tools.logical_tools[name]
        logical_tools.append(
            {
                "name": name,
                "enabled": settings.enabled,
                "provider": settings.provider,
                "description": settings.description,
                "builtin_tool": settings.builtin_tool,
                "server": settings.server,
                "tool": settings.tool,
            }
        )
    return logical_tools


def _resolve_instruction_sources(config: AppConfig, role: str, *, constraint_mode: str = "default") -> list[str]:
    if constraint_mode in {"runtime_only", "bypass"}:
        return []

    default_root = files("support_ope_agents.instructions.defaults")
    default_common = default_root / "common.md"
    default_role = default_root / f"{role}.md"
    sources: list[str] = []
    if _path_exists(default_common):
        sources.append(str(default_common))
    if _path_exists(default_role):
        sources.append(str(default_role))

    override_root = config.config_paths.instructions_path
    if override_root is not None:
        common_override = override_root / "common.md"
        role_override = override_root / f"{role}.md"
        if common_override.exists():
            sources.append(str(common_override))
        if role_override.exists():
            sources.append(str(role_override))
    return sources


def _build_agent_entry(
    config: AppConfig,
    tool_registry: ToolRegistry,
    definition: AgentDefinition,
    instructions: dict[str, object],
) -> dict[str, object]:
    settings = config.agents.get(definition.role)
    instruction_entry = next(
        (item for item in _instruction_role_entries(instructions) if item.get("role") == definition.role),
        None,
    )
    return {
        "role": definition.role,
        "description": definition.description,
        "kind": definition.kind,
        "parent_role": definition.parent_role,
        "enabled": bool(getattr(settings, "enabled", True)) if settings is not None else True,
        "settings": settings.model_dump() if settings is not None else {},
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "provider": tool.provider,
                "target": tool.target,
            }
            for tool in tool_registry.get_tools(definition.role)
        ],
        "instruction": instruction_entry,
    }


def _build_control_points(config: AppConfig, instructions: dict[str, object]) -> list[dict[str, object]]:
    override_root = config.config_paths.instructions_path
    control_points = [
        _control_point(
            control_point_id="workflow.approval_node",
            category="configuration",
            owner="workflow",
            origin="config.workflow.approval_node",
            condition="always",
            effect=f"approval gate node is '{config.workflow.approval_node}'",
            overrideable=True,
            config_key="workflow.approval_node",
            docs_refs=["docs/configuration.md", "docs/customer-support-deepagents-design.md"],
            code_refs=["src/support_ope_agents/config/models.py", "src/support_ope_agents/workflow/case_workflow.py"],
        ),
        _control_point(
            control_point_id="workflow.auto_compress",
            category="configuration",
            owner="workflow",
            origin="config.workflow.auto_compress",
            condition="always",
            effect=f"workflow-level auto compression is {'enabled' if config.workflow.auto_compress else 'disabled'}",
            overrideable=True,
            config_key="workflow.auto_compress",
            docs_refs=["docs/configuration.md", "docs/customer-support-deepagents-design.md"],
            code_refs=["src/support_ope_agents/config/models.py"],
        ),
        _control_point(
            control_point_id="agent.supervisor.auto_generate_report",
            category="configuration",
            owner="SuperVisorAgent",
            origin="config.agents.SuperVisorAgent.auto_generate_report",
            condition="state.status reaches configured report_on target",
            effect=f"auto report generation is {'enabled' if config.agents.SuperVisorAgent.auto_generate_report else 'disabled'}",
            overrideable=True,
            config_key="agents.SuperVisorAgent.auto_generate_report",
            docs_refs=["docs/configuration.md", "docs/agents/supervisor-agent.md"],
            code_refs=["src/support_ope_agents/config/models.py", "src/support_ope_agents/runtime/service.py"],
        ),
        _control_point(
            control_point_id="agent.intake.pii_mask",
            category="configuration",
            owner="IntakeAgent",
            origin="config.agents.IntakeAgent.pii_mask.enabled",
            condition="IntakeAgent prepare/mask phase",
            effect=f"PII mask is {'enabled' if config.agents.IntakeAgent.pii_mask.enabled else 'disabled'} by default",
            overrideable=True,
            config_key="agents.IntakeAgent.pii_mask.enabled",
            docs_refs=["docs/configuration.md", "docs/agents/common.md"],
            code_refs=["src/support_ope_agents/config/models.py", "src/support_ope_agents/agents/intake_agent.py"],
        ),
        _control_point(
            control_point_id="agent.escalation.rules",
            category="configuration",
            owner="BackSupportEscalationAgent",
            origin="config.agents.BackSupportEscalationAgent.escalation",
            condition="investigation phase decides escalation_required",
            effect="uncertainty markers and missing artifacts influence escalation branching",
            overrideable=True,
            config_key="agents.BackSupportEscalationAgent.escalation",
            docs_refs=["docs/configuration.md", "docs/agents/back-support-escalation-agent.md"],
            code_refs=["src/support_ope_agents/config/models.py", "src/support_ope_agents/agents/supervisor_agent.py"],
        ),
        _control_point(
            control_point_id="instruction.default_stack",
            category="instruction",
            owner="all-agents",
            origin="support_ope_agents.instructions.defaults",
            condition="instruction resolution",
            effect="default common and role instructions are concatenated first",
            overrideable=True,
            config_key=None,
            docs_refs=["docs/configuration.md", "docs/agents/common.md"],
            code_refs=["src/support_ope_agents/instructions/loader.py", "src/support_ope_agents/instructions/defaults/common.md"],
        ),
        _control_point(
            control_point_id="instruction.override_stack",
            category="instruction",
            owner="all-agents",
            origin="config.config_paths.instructions_path",
            condition="override root exists",
            effect=f"override instruction root is {str(override_root) if override_root is not None else 'not configured'}",
            overrideable=True,
            config_key="config_paths.instructions_path",
            docs_refs=["docs/configuration.md", "docs/agents/supervisor-agent.md"],
            code_refs=["src/support_ope_agents/instructions/loader.py"],
        ),
        _control_point(
            control_point_id="workflow.route_after_intake",
            category="workflow",
            owner="case_workflow",
            origin="workflow._route_after_intake",
            condition="state.status after intake",
            effect="routes to wait_for_customer_input or investigation",
            overrideable=False,
            config_key=None,
            docs_refs=["docs/customer-support-deepagents-design.md", "docs/agents/intake-agent.md"],
            code_refs=["src/support_ope_agents/workflow/case_workflow.py"],
        ),
        _control_point(
            control_point_id="workflow.route_after_investigation",
            category="workflow",
            owner="case_workflow",
            origin="workflow._route_after_investigation",
            condition="state.escalation_required",
            effect="routes to escalation_review or draft_review",
            overrideable=False,
            config_key=None,
            docs_refs=["docs/customer-support-deepagents-design.md", "docs/agents/supervisor-agent.md"],
            code_refs=["src/support_ope_agents/workflow/case_workflow.py", "src/support_ope_agents/agents/supervisor_agent.py"],
        ),
        _control_point(
            control_point_id="workflow.route_after_approval",
            category="workflow",
            owner="case_workflow",
            origin="workflow._route_after_approval",
            condition="state.approval_decision",
            effect="routes to ticket update, draft review, reinvestigation, or end",
            overrideable=False,
            config_key=None,
            docs_refs=["docs/customer-support-deepagents-design.md", "docs/agents/approval-agent.md"],
            code_refs=["src/support_ope_agents/workflow/case_workflow.py"],
        ),
    ]

    for role_entry in _instruction_role_entries(instructions):
        control_points.append(
            _control_point(
                control_point_id=f"instruction.role.{role_entry['role']}",
                category="instruction",
                owner=str(role_entry["role"]),
                origin=str(role_entry["default_path"]),
                condition="agent instruction resolution",
                effect="resolved instruction stack is available for this role",
                overrideable=True,
                config_key="config_paths.instructions_path",
                docs_refs=["docs/configuration.md", _agent_doc_path(str(role_entry["role"]))],
                code_refs=[str(role_entry["default_path"]), "src/support_ope_agents/instructions/loader.py"],
            )
        )
    return control_points


def _control_point(
    *,
    control_point_id: str,
    category: str,
    owner: str,
    origin: str,
    condition: str,
    effect: str,
    overrideable: bool,
    config_key: str | None,
    docs_refs: list[str],
    code_refs: list[str],
) -> dict[str, object]:
    return {
        "id": control_point_id,
        "category": category,
        "owner": owner,
        "origin": origin,
        "condition": condition,
        "effect": effect,
        "overrideable": overrideable,
        "config_key": config_key,
        "docs_refs": docs_refs,
        "code_refs": code_refs,
    }


def _agent_doc_path(role: str) -> str:
    return {
        "SuperVisorAgent": "docs/agents/supervisor-agent.md",
        "ObjectiveEvaluator": "docs/agents/objective-evaluator.md",
        "IntakeAgent": "docs/agents/intake-agent.md",
        "InvestigateAgent": "docs/agents/common.md",
        "BackSupportEscalationAgent": "docs/agents/back-support-escalation-agent.md",
        "BackSupportInquiryWriterAgent": "docs/agents/back-support-inquiry-writer-agent.md",
        "ApprovalAgent": "docs/agents/approval-agent.md",
        "TicketUpdateAgent": "docs/agents/ticket-update-agent.md",
    }.get(role, "docs/agents/common.md")


def _effective_workflow_kind(state: CaseState) -> str:
    workflow_kind = str(state.get("workflow_kind") or "").strip()
    intake_category = str(state.get("intake_category") or "").strip()
    valid_values = {"specification_inquiry", "incident_investigation", "ambiguous_case"}
    if workflow_kind not in valid_values:
        return intake_category if intake_category in valid_values else "ambiguous_case"
    if workflow_kind == "ambiguous_case" and intake_category in {"specification_inquiry", "incident_investigation"}:
        return intake_category
    return workflow_kind


def _approval_route(state: CaseState) -> str:
    if str(state.get("status") or "") == CaseStatuses.CLOSED or str(state.get("ticket_update_result") or "").strip():
        return "ticket_update_subgraph"
    decision = str(state.get("approval_decision") or "").strip().lower()
    if decision in {"approved", "approve"}:
        return "ticket_update_subgraph"
    if decision in {"rejected", "reject"}:
        return "draft_review"
    if decision == "reinvestigate":
        return "investigation"
    return "__end__"


def _resolve_used_roles(workflow_path: list[str], workflow_kind: str) -> list[str]:
    del workflow_kind
    ordered_roles: list[str] = ["IntakeAgent", "SuperVisorAgent"]
    if "wait_for_customer_input" in workflow_path:
        return ordered_roles
    if "investigation" in workflow_path:
        ordered_roles.append("InvestigateAgent")
    if "escalation_review" in workflow_path:
        ordered_roles.extend(["BackSupportEscalationAgent", "BackSupportInquiryWriterAgent", "ApprovalAgent"])
    elif "draft_review" in workflow_path:
        ordered_roles.append("ApprovalAgent")
    if "ticket_update_execute" in workflow_path:
        ordered_roles.append("TicketUpdateAgent")
    return ordered_roles


def _workflow_catalog() -> tuple[list[str], list[dict[str, object]]]:
    return (
        [
            "receive_case",
            "intake_prepare",
            "intake_mask",
            "intake_hydrate_tickets",
            "intake_classify",
            "intake_finalize",
            "supervisor_subgraph",
            "investigation",
            "draft_review",
            "escalation_review",
            "wait_for_customer_input",
            "wait_for_approval",
            "ticket_update_subgraph",
            "ticket_update_prepare",
            "ticket_update_execute",
        ],
        [
            {"from": "START", "to": "receive_case", "type": "direct"},
            {"from": "receive_case", "to": "intake_subgraph", "type": "direct"},
            {"from": "intake_prepare", "to": "intake_mask", "type": "direct"},
            {"from": "intake_mask", "to": "intake_hydrate_tickets", "type": "direct"},
            {"from": "intake_hydrate_tickets", "to": "intake_classify", "type": "direct"},
            {"from": "intake_classify", "to": "intake_quality_gate", "type": "direct"},
            {"from": "intake_quality_gate", "to": "intake_finalize", "type": "direct"},
            {
                "from": "intake_subgraph",
                "to": "wait_for_customer_input",
                "type": "conditional",
                "condition": "state.status == 'WAITING_CUSTOMER_INPUT'",
                "control_point_id": "workflow.route_after_intake.wait_for_customer_input",
            },
            {
                "from": "intake_subgraph",
                "to": "supervisor_subgraph",
                "type": "conditional",
                "condition": "otherwise",
                "control_point_id": "workflow.route_after_intake.investigation",
            },
            {"from": "supervisor_subgraph", "to": "wait_for_approval", "type": "direct"},
            {
                "from": "investigation",
                "to": "escalation_review",
                "type": "conditional",
                "condition": "state.escalation_required is true",
                "control_point_id": "workflow.route_after_investigation.escalation_review",
            },
            {
                "from": "investigation",
                "to": "draft_review",
                "type": "conditional",
                "condition": "otherwise",
                "control_point_id": "workflow.route_after_investigation.draft_review",
            },
            {"from": "escalation_review", "to": "wait_for_approval", "type": "direct"},
            {"from": "draft_review", "to": "wait_for_approval", "type": "direct"},
            {
                "from": "wait_for_approval",
                "to": "ticket_update_subgraph",
                "type": "conditional",
                "condition": "state.approval_decision in {'approved', 'approve'}",
                "control_point_id": "workflow.route_after_approval.approved",
            },
            {
                "from": "wait_for_approval",
                "to": "supervisor_subgraph",
                "type": "conditional",
                "condition": "state.approval_decision in {'rejected', 'reject'}",
                "control_point_id": "workflow.route_after_approval.rejected",
            },
            {
                "from": "wait_for_approval",
                "to": "supervisor_subgraph",
                "type": "conditional",
                "condition": "state.approval_decision == 'reinvestigate'",
                "control_point_id": "workflow.route_after_approval.reinvestigate",
            },
            {
                "from": "wait_for_approval",
                "to": "END",
                "type": "conditional",
                "condition": "otherwise",
                "control_point_id": "workflow.route_after_approval.end",
            },
            {"from": "ticket_update_subgraph", "to": "END", "type": "direct"},
            {"from": "ticket_update_prepare", "to": "ticket_update_execute", "type": "direct"},
        ],
    )


def _build_runtime_decision_log(
    state: CaseState,
    workflow_path: list[str],
    config: AppConfig,
) -> list[dict[str, object]]:
    decisions: list[dict[str, object]] = [
        {
            "control_point_id": f"execution_mode.{str(state.get('execution_mode') or 'unknown')}",
            "category": "execution",
            "outcome": str(state.get("execution_mode") or "unknown"),
            "detail": "実行モードに応じて plan/action の分岐を行いました。",
        },
        {
            "control_point_id": "agent.intake.pii_mask",
            "category": "configuration",
            "outcome": "enabled" if config.agents.IntakeAgent.pii_mask.enabled else "disabled",
            "detail": f"IntakeAgent の PII マスク既定値は {'有効' if config.agents.IntakeAgent.pii_mask.enabled else '無効'}です。",
        },
    ]

    if "wait_for_customer_input" in workflow_path:
        decisions.append(
            {
                "control_point_id": "workflow.route_after_intake.wait_for_customer_input",
                "category": "workflow",
                "outcome": "taken",
                "detail": "Intake 結果により顧客への追加確認へ遷移しました。",
            }
        )
        return decisions

    decisions.append(
        {
            "control_point_id": "workflow.route_after_intake.investigation",
            "category": "workflow",
            "outcome": "taken",
            "detail": "Intake 完了後に investigation へ遷移しました。",
        }
    )

    if bool(state.get("escalation_required")):
        decisions.append(
            {
                "control_point_id": "workflow.route_after_investigation.escalation_review",
                "category": "workflow",
                "outcome": "taken",
                "detail": "追加支援が必要と判断し escalation_review に進みました。",
            }
        )
        decisions.append(
            {
                "control_point_id": "agent.escalation.rules",
                "category": "configuration",
                "outcome": "escalated",
                "detail": str(state.get("escalation_reason") or "エスカレーション判定ルールにより追加支援が必要とされました。"),
            }
        )
    else:
        decisions.append(
            {
                "control_point_id": "workflow.route_after_investigation.draft_review",
                "category": "workflow",
                "outcome": "taken",
                "detail": "調査結果から draft_review へ進みました。",
            }
        )
    if "wait_for_approval" in workflow_path:
        approval_route = _approval_route(state)
        decisions.append(
            {
                "control_point_id": f"workflow.route_after_approval.{approval_route}",
                "category": "workflow",
                "outcome": approval_route,
                "detail": f"承認判定により {approval_route} へ遷移しました。",
            }
        )

    return decisions


def _result_label(state: CaseState) -> str:
    if bool(state.get("escalation_required")):
        return "エスカレーションが必要だった"
    if str(state.get("draft_response") or "").strip():
        return "確実な回答が得られた"
    if str(state.get("status") or "") == CaseStatuses.WAITING_CUSTOMER_INPUT:
        return "追加の顧客入力が必要"
    return "回答ドラフトは作成されたが追加確認が必要"


def _instruction_excerpt(text: str) -> str:
    normalized = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return normalized[:160] + ("..." if len(normalized) > 160 else "")


def _path_exists(path: _ReadablePath | Path | Any) -> bool:
    return bool(cast(Any, path).exists())


def _instruction_role_entries(instructions: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], instructions.get("roles") or [])


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            return default
    return default


def _infer_instruction_constraints(text: str, *, max_items: int = 6) -> list[str]:
    directive_markers = (
        "必ず",
        "してください",
        "しないでください",
        "優先",
        "残してください",
        "記述してください",
        "確認してください",
        "明示してください",
        "分離してください",
        "見つからない場合",
        "使わず",
        "そのまま出さず",
    )
    inferred: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*]\s+", "", line).strip()
        if not any(marker in line for marker in directive_markers):
            continue
        if line not in inferred:
            inferred.append(line)
        if len(inferred) >= max_items:
            break
    return inferred