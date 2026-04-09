from __future__ import annotations

import argparse
import json
from typing import Any

from support_ope_agents.agents import DeepAgentFactory
from support_ope_agents.config import load_config
from support_ope_agents.instructions import InstructionLoader
from support_ope_agents.memory import CaseMemoryStore
from support_ope_agents.tools import ToolRegistry
from support_ope_agents.workflow import build_case_workflow


def _build_runtime(config_path: str):
    config = load_config(config_path)
    memory_store = CaseMemoryStore(config)
    instruction_loader = InstructionLoader(config, memory_store)
    tool_registry = ToolRegistry(config)
    agent_factory = DeepAgentFactory(config, instruction_loader, tool_registry, memory_store)
    return config, memory_store, instruction_loader, tool_registry, agent_factory


def _cmd_init_case(args: argparse.Namespace) -> int:
    _, memory_store, instruction_loader, _, agent_factory = _build_runtime(args.config)
    case_paths = memory_store.initialize_case(args.case_id)
    for definition in agent_factory.build_default_definitions():
        memory_store.ensure_agent_working_memory(args.case_id, definition.role)
        instruction_loader.ensure_override_file(args.case_id, definition.role)

    print(case_paths.root)
    return 0


def _cmd_print_workflow(args: argparse.Namespace) -> int:
    _build_runtime(args.config)
    app = build_case_workflow()
    graph = app.get_graph()
    try:
        print(graph.draw_ascii())
    except ImportError:
        node_names = sorted(node.id for node in graph.nodes.values())
        print("Workflow nodes:")
        for node_name in node_names:
            print(f"- {node_name}")
    return 0


def _cmd_describe_agents(args: argparse.Namespace) -> int:
    _, _, _, _, agent_factory = _build_runtime(args.config)
    agents: list[dict[str, Any]] = []
    for definition in agent_factory.build_default_definitions():
        agent = agent_factory.build_agent(args.case_id, definition)
        if isinstance(agent, dict):
            agents.append(agent)
        else:
            agents.append({"role": definition.role, "description": definition.description})
    print(json.dumps(agents, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="support-ope-agents CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yml", help="Path to config.yml")

    init_case = subparsers.add_parser("init-case", help="Initialize case workspace", parents=[common])
    init_case.add_argument("case_id", help="Case identifier")
    init_case.set_defaults(func=_cmd_init_case)

    print_workflow = subparsers.add_parser("print-workflow", help="Print workflow diagram", parents=[common])
    print_workflow.set_defaults(func=_cmd_print_workflow)

    describe_agents = subparsers.add_parser("describe-agents", help="Describe default agent layout", parents=[common])
    describe_agents.add_argument("case_id", help="Case identifier")
    describe_agents.set_defaults(func=_cmd_describe_agents)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())