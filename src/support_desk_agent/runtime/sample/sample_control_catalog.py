from __future__ import annotations

from typing import cast

from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.config.models import AppConfig
from support_desk_agent.instructions.loader import InstructionLoader
from support_desk_agent.models.state import CaseState
from support_desk_agent.runtime.production.control_catalog import _approval_route
from support_desk_agent.runtime.production.control_catalog import _build_agent_entry
from support_desk_agent.runtime.production.control_catalog import _build_control_points
from support_desk_agent.runtime.production.control_catalog import _build_instruction_catalog
from support_desk_agent.runtime.production.control_catalog import _build_instruction_resolution_entry
from support_desk_agent.runtime.production.control_catalog import _build_logical_tool_catalog
from support_desk_agent.runtime.production.control_catalog import _build_runtime_decision_log
from support_desk_agent.runtime.production.control_catalog import _coerce_int
from support_desk_agent.runtime.production.control_catalog import _effective_workflow_kind
from support_desk_agent.runtime.production.control_catalog import _infer_instruction_constraints
from support_desk_agent.runtime.production.control_catalog import _instruction_role_entries
from support_desk_agent.runtime.production.control_catalog import _load_common_instruction_text
from support_desk_agent.runtime.production.control_catalog import _result_label
from support_desk_agent.runtime.runtime_harness_manager import RuntimeHarnessManager
from support_desk_agent.tools.registry import ToolRegistry
from support_desk_agent.workflow.sample.sample_case_workflow import CaseWorkflow as SampleCaseWorkflow


def build_sample_control_catalog(
    *,
    config: AppConfig,
    tool_registry: ToolRegistry,
    agent_definitions: list[AgentDefinition],
    runtime_harness_manager: RuntimeHarnessManager | None = None,
) -> dict[str, object]:
    harness = runtime_harness_manager or RuntimeHarnessManager(config)
    workflow_nodes, workflow_edges = _sample_workflow_catalog()

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


def build_sample_runtime_audit(
    *,
    case_id: str,
    state: CaseState,
    config: AppConfig,
    instruction_loader: InstructionLoader,
    runtime_harness_manager: RuntimeHarnessManager | None = None,
) -> dict[str, object]:
    harness = runtime_harness_manager or RuntimeHarnessManager(config)
    workflow_path = list(SampleCaseWorkflow().reconstruct_main_workflow_path(state))
    workflow_kind = _effective_workflow_kind(state)
    used_roles = _resolve_sample_used_roles(workflow_path, workflow_kind)
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
            "runtime_mode": "sample",
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
            for item in cast(list[dict[str, object]], decision_log)
            if str(item.get("control_point_id") or "")
        ],
    }


def _resolve_sample_used_roles(workflow_path: list[str], workflow_kind: str) -> list[str]:
    del workflow_kind
    ordered_roles: list[str] = ["IntakeAgent", "SuperVisorAgent"]
    if "wait_for_customer_input" in workflow_path:
        return ordered_roles
    if "investigation" in workflow_path:
        ordered_roles.append("InvestigateAgent")
    if "ticket_update_execute" in workflow_path:
        ordered_roles.append("TicketUpdateAgent")
    return ordered_roles


def _sample_workflow_catalog() -> tuple[list[str], list[dict[str, object]]]:
    return (
        [
            "receive_case",
            "intake_prepare",
            "intake_classify",
            "intake_mcp_tickets",
            "intake_ticket_followup_decision",
            "intake_request_customer_input",
            "intake_finalize",
            "supervisor_subgraph",
            "investigation",
            "draft_review",
            "escalation_review",
            "wait_for_approval",
            "ticket_update_subgraph",
            "ticket_update_prepare",
            "ticket_update_execute",
        ],
        [
            {"from": "START", "to": "receive_case", "type": "direct"},
            {"from": "receive_case", "to": "intake_subgraph", "type": "direct"},
            {"from": "intake_prepare", "to": "intake_classify", "type": "direct"},
            {"from": "intake_classify", "to": "intake_mcp_tickets", "type": "direct"},
            {"from": "intake_mcp_tickets", "to": "intake_ticket_followup_decision", "type": "direct"},
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
            {"from": "intake_ticket_followup_decision", "to": "intake_finalize", "type": "conditional", "condition": "investigate"},
            {"from": "intake_ticket_followup_decision", "to": "intake_request_customer_input", "type": "conditional", "condition": "request_customer_input"},
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
            {"from": "draft_review", "to": "wait_for_approval", "type": "direct"},
            {"from": "escalation_review", "to": "wait_for_approval", "type": "direct"},
            {
                "from": "wait_for_approval",
                "to": "ticket_update_subgraph",
                "type": "conditional",
                "condition": "state.approval_decision in {'approved', 'approve'}",
                "control_point_id": "workflow.route_after_approval.approved",
            },
            {
                "from": "wait_for_approval",
                "to": "draft_review",
                "type": "conditional",
                "condition": "state.approval_decision in {'rejected', 'reject'}",
                "control_point_id": "workflow.route_after_approval.rejected",
            },
            {
                "from": "wait_for_approval",
                "to": "investigation",
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