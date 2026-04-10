from __future__ import annotations

import argparse
import json
from typing import Any

from support_ope_agents.runtime import RuntimeService, build_runtime_context
from support_ope_agents.tools.doc_generator import export_tool_docs


def _build_service(config_path: str) -> RuntimeService:
    return RuntimeService(build_runtime_context(config_path))


def _cmd_init_case(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    resolved_case_id = service.resolve_case_id(prompt=args.prompt, workspace_path=args.workspace_path)
    print(service.initialize_case(resolved_case_id, workspace_path=args.workspace_path))
    return 0


def _cmd_print_workflow(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    print("Workflow nodes:")
    for node_name in service.print_workflow_nodes():
        print(f"- {node_name}")
    return 0


def _cmd_describe_agents(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    resolved_case_id = service.resolve_case_id(prompt=args.prompt)
    print(json.dumps(service.describe_agents(resolved_case_id), ensure_ascii=False, indent=2))
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    result = service.plan(
        prompt=args.prompt,
        workspace_path=args.workspace_path,
        external_ticket_id=args.external_ticket_id,
        internal_ticket_id=args.internal_ticket_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_action(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    result = service.action(
        prompt=args.prompt,
        workspace_path=args.workspace_path,
        trace_id=args.trace_id,
        execution_plan=args.execution_plan,
        external_ticket_id=args.external_ticket_id,
        internal_ticket_id=args.internal_ticket_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_resume_customer_input(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    result = service.resume_customer_input(
        case_id=args.case_id,
        trace_id=args.trace_id,
        workspace_path=args.workspace_path,
        additional_input=args.additional_input,
        answer_key=args.answer_key,
        external_ticket_id=args.external_ticket_id,
        internal_ticket_id=args.internal_ticket_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_export_tool_docs(args: argparse.Namespace) -> int:
    generated = export_tool_docs(args.config, args.output_dir)
    print(json.dumps([str(path) for path in generated], ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="support-ope-agents CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yml", help="Path to config.yml")

    init_case = subparsers.add_parser("init-case", help="Initialize case workspace", parents=[common])
    init_case.add_argument("--prompt", required=True, help="User input used to resolve case_id")
    init_case.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    init_case.set_defaults(func=_cmd_init_case)

    print_workflow = subparsers.add_parser("print-workflow", help="Print workflow diagram", parents=[common])
    print_workflow.set_defaults(func=_cmd_print_workflow)

    describe_agents = subparsers.add_parser("describe-agents", help="Describe default agent layout", parents=[common])
    describe_agents.add_argument("--prompt", required=True, help="User input used to resolve case_id")
    describe_agents.set_defaults(func=_cmd_describe_agents)

    plan = subparsers.add_parser("plan", help="Create an execution plan for a case", parents=[common])
    plan.add_argument("prompt", help="User request for planning")
    plan.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    plan.add_argument("--external-ticket-id", default=None, help="Explicit external ticket ID. If omitted, derive from trace_id")
    plan.add_argument("--internal-ticket-id", default=None, help="Explicit internal ticket ID. If omitted, derive from trace_id")
    plan.set_defaults(func=_cmd_plan)

    action = subparsers.add_parser("action", help="Execute action mode for a case", parents=[common])
    action.add_argument("prompt", help="User request for action execution")
    action.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    action.add_argument("--trace-id", default=None, help="Trace identifier from plan mode")
    action.add_argument("--execution-plan", default=None, help="Optional execution plan text")
    action.add_argument("--external-ticket-id", default=None, help="Explicit external ticket ID. If omitted, derive from trace_id")
    action.add_argument("--internal-ticket-id", default=None, help="Explicit internal ticket ID. If omitted, derive from trace_id")
    action.set_defaults(func=_cmd_action)

    resume_customer_input = subparsers.add_parser(
        "resume-customer-input",
        help="Resume a paused trace with additional customer input",
        parents=[common],
    )
    resume_customer_input.add_argument("additional_input", help="Additional customer response to a follow-up question")
    resume_customer_input.add_argument("--case-id", required=True, help="Case identifier to resume")
    resume_customer_input.add_argument("--trace-id", required=True, help="Trace identifier to resume")
    resume_customer_input.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    resume_customer_input.add_argument("--answer-key", default=None, help="Field key of the follow-up question being answered")
    resume_customer_input.add_argument("--external-ticket-id", default=None, help="Explicit external ticket ID override")
    resume_customer_input.add_argument("--internal-ticket-id", default=None, help="Explicit internal ticket ID override")
    resume_customer_input.set_defaults(func=_cmd_resume_customer_input)

    export_tool_docs = subparsers.add_parser(
        "export-tool-docs",
        help="Export semi-automatic tool docs drafts from ToolRegistry",
        parents=[common],
    )
    export_tool_docs.add_argument(
        "--output-dir",
        default="docs/tools/generated",
        help="Directory where generated markdown drafts are written",
    )
    export_tool_docs.set_defaults(func=_cmd_export_tool_docs)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())