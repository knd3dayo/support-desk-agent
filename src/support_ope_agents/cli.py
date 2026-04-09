from __future__ import annotations

import argparse
import json
from typing import Any

from support_ope_agents.runtime import RuntimeService, build_runtime_context


def _build_service(config_path: str) -> RuntimeService:
    return RuntimeService(build_runtime_context(config_path))


def _cmd_init_case(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    resolved_case_id = service.resolve_case_id(prompt=args.prompt)
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
    result = service.plan(prompt=args.prompt, workspace_path=args.workspace_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_action(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    result = service.action(
        prompt=args.prompt,
        workspace_path=args.workspace_path,
        trace_id=args.trace_id,
        execution_plan=args.execution_plan,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="support-ope-agents CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yml", help="Path to config.yml")

    init_case = subparsers.add_parser("init-case", help="Initialize case workspace", parents=[common])
    init_case.add_argument("--prompt", required=True, help="User input used to resolve case_id")
    init_case.add_argument("--workspace-path", default=None, help="Optional external workspace path to register")
    init_case.set_defaults(func=_cmd_init_case)

    print_workflow = subparsers.add_parser("print-workflow", help="Print workflow diagram", parents=[common])
    print_workflow.set_defaults(func=_cmd_print_workflow)

    describe_agents = subparsers.add_parser("describe-agents", help="Describe default agent layout", parents=[common])
    describe_agents.add_argument("--prompt", required=True, help="User input used to resolve case_id")
    describe_agents.set_defaults(func=_cmd_describe_agents)

    plan = subparsers.add_parser("plan", help="Create an execution plan for a case", parents=[common])
    plan.add_argument("prompt", help="User request for planning")
    plan.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    plan.set_defaults(func=_cmd_plan)

    action = subparsers.add_parser("action", help="Execute action mode for a case", parents=[common])
    action.add_argument("prompt", help="User request for action execution")
    action.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    action.add_argument("--trace-id", default=None, help="Trace identifier from plan mode")
    action.add_argument("--execution-plan", default=None, help="Optional execution plan text")
    action.set_defaults(func=_cmd_action)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())