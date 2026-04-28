from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast
from support_ope_agents.models.state import CaseState

from support_ope_agents.agents.objective_evaluator import ObjectiveEvaluator
from support_ope_agents.agents.roles import OBJECTIVE_EVALUATOR
from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_ope_agents.agents.sample.sample_supervisor_agent import SampleSupervisorAgent
from support_ope_agents.config.loader import load_config
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
from support_ope_agents.runtime.conversation_messages import extract_result_output_text
from support_ope_agents.runtime import build_runtime_service
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.workspace_evidence import find_evidence_log_file
from support_ope_agents.tools.doc_generator import export_tool_docs


INVESTIGATE_STANDALONE_EVALUATION_APPENDIX = """
この評価は InvestigateAgent 単体実行の回答品質評価です。
SuperVisorAgent や他エージェントの不在そのものは減点対象にせず、次を優先して評価してください。
- 問い合わせに対して、結論・原因候補・根拠・次アクションが実務に足る粒度で返っているか
- evidence や添付を実際に使った形跡があるか
- 断定できない場合に不確実性と追加確認事項を適切に示しているか
- InvestigateAgent の working memory が存在する場合、その内容と最終回答が整合しているか
agent_evaluations は InvestigateAgent を中心に評価してください。
""".strip()

INVESTIGATE_CHECKLIST_TEMPLATES: dict[str, list[str]] = {
    "basic": [
        "問い合わせに対する結論または現時点の判断が明記されていること",
        "ログや添付に基づく根拠が示されていること",
        "次に取るべきアクションまたは追加確認事項が示されていること",
    ],
    "incident-log": [
        "障害原因候補または有力仮説が示されていること",
        "参照したログ断片または対象ファイルが回答と対応していること",
        "断定できない場合に不足情報と確認手順が示されていること",
    ],
}


def _build_service(config_path: str):
    return build_runtime_service(config_path)


def _extract_result_output(result: Any) -> str:
    return extract_result_output_text(result) or format_result(result)


def _resolve_case_id(memory_store: CaseMemoryStore, workspace_path: str, explicit_case_id: str | None = None) -> str:
    if explicit_case_id:
        return explicit_case_id
    marker = memory_store.read_case_id_marker(workspace_path)
    if marker:
        return marker
    return Path(workspace_path).expanduser().resolve().name


def _collect_evaluation_artifact_paths(memory_store: CaseMemoryStore, case_id: str, workspace_path: str) -> list[str]:
    paths = memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
    collected: list[str] = []
    for directory in (paths.evidence_dir, paths.artifacts_dir):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                try:
                    collected.append(path.relative_to(paths.root).as_posix())
                except ValueError:
                    collected.append(str(path))
    return collected


def _build_investigate_standalone_evidence(
    *,
    case_id: str,
    workspace_path: str,
    query: str,
    investigation_result_text: str,
    artifact_paths: list[str],
    working_memory: str,
    checklist: list[str],
) -> dict[str, Any]:
    evidence_log_path = find_evidence_log_file(workspace_path)
    return {
        "case_id": case_id,
        "trace_id": "investigate-standalone",
        "status": "completed",
        "workflow_kind": "investigate_standalone",
        "raw_issue": query,
        "draft_response": "",
        "investigation_summary": investigation_result_text,
        "escalation_reason": "",
        "escalation_summary": "",
        "escalation_draft": "",
        "log_analysis_summary": investigation_result_text,
        "knowledge_retrieval_adopted_sources": [],
        "shared_memory": {"context": "", "progress": "", "summary": ""},
        "agent_memories": {"InvestigateAgent": working_memory},
        "memory_findings": [],
        "artifact_paths": artifact_paths,
        "user_checklist": checklist,
        "expected_criteria": [],
        "agent_errors": [],
        "evaluation_scope": "InvestigateAgent standalone",
        "workspace_path": workspace_path,
        "evidence_log_path": str(evidence_log_path) if evidence_log_path is not None else "",
    }


def _resolve_checklist(args: argparse.Namespace) -> list[str]:
    resolved: list[str] = []
    template_name = str(getattr(args, "checklist_template", "") or "").strip()
    if template_name:
        resolved.extend(INVESTIGATE_CHECKLIST_TEMPLATES.get(template_name, []))
    resolved.extend(list(args.checklist or []))
    return resolved


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


def _cmd_describe_control_catalog(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    print(json.dumps(service.describe_control_catalog(), ensure_ascii=False, indent=2))
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


def _cmd_generate_report(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    result = service.generate_support_improvement_report(
        case_id=args.case_id,
        trace_id=args.trace_id,
        workspace_path=args.workspace_path,
        checklist=list(args.checklist or []),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_checkpoint_status(args: argparse.Namespace) -> int:
    service = _build_service(args.config)
    result = service.checkpoint_status(
        case_id=args.case_id,
        workspace_path=args.workspace_path,
        trace_id=args.trace_id,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_evaluate_investigate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    memory_store = CaseMemoryStore(config)
    case_id = _resolve_case_id(memory_store, args.workspace_path, explicit_case_id=args.case_id)
    investigate_agent = SampleInvestigateAgent(config)
    investigate_result = investigate_agent.execute(
        query=args.prompt,
        workspace_path=args.workspace_path,
    )
    investigate_result_text = _extract_result_output(investigate_result)
    working_memory = investigate_agent.read_investigate_working_memory(case_id, args.workspace_path)
    artifact_paths = _collect_evaluation_artifact_paths(memory_store, case_id, args.workspace_path)
    instruction_loader = InstructionLoader(config, memory_store)
    base_instruction = instruction_loader.load(case_id, OBJECTIVE_EVALUATOR)
    instruction_text = "\n\n".join(part for part in (base_instruction, INVESTIGATE_STANDALONE_EVALUATION_APPENDIX) if part)
    checklist = _resolve_checklist(args)
    evaluator = ObjectiveEvaluator(config=config, instruction_text=instruction_text)
    evaluation = evaluator.evaluate(
        evidence=_build_investigate_standalone_evidence(
            case_id=case_id,
            workspace_path=args.workspace_path,
            query=args.prompt,
            investigation_result_text=investigate_result_text,
            artifact_paths=artifact_paths,
            working_memory=working_memory,
            checklist=checklist,
        )
    )
    payload = {
        "case_id": case_id,
        "workspace_path": args.workspace_path,
        "prompt": args.prompt,
        "investigation_result": investigate_result_text,
        "artifact_paths": artifact_paths,
        "checklist": checklist,
        "evaluation": evaluation.model_dump(),
    }
    output_path = str(getattr(args, "output", "") or "").strip()
    if output_path:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["output_path"] = str(target)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_run_sample_supervisor(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    memory_store = CaseMemoryStore(config)
    case_id = _resolve_case_id(memory_store, args.workspace_path, explicit_case_id=args.case_id)
    investigate_agent = SampleInvestigateAgent(config)
    supervisor = SampleSupervisorAgent(config=config, investigate_executor=investigate_agent)

    state: CaseState = {
        "case_id": case_id,
        "workspace_path": args.workspace_path,
        "raw_issue": args.prompt,
    }
    investigated_state = supervisor.execute_investigation(state)
    # route_after_investigation expects a plain mapping type; cast to satisfy static type
    route = supervisor.route_after_investigation(cast(dict[str, object], investigated_state))
    if route == "escalation_review":
        final_state = supervisor.execute_escalation_review(investigated_state)
    else:
        final_state = supervisor.execute_draft_review(investigated_state)

    payload = {
        "case_id": case_id,
        "workspace_path": args.workspace_path,
        "prompt": args.prompt,
        "route": route,
        "state": final_state,
    }
    output_path = str(getattr(args, "output", "") or "").strip()
    if output_path:
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["output_path"] = str(target)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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

    describe_control_catalog = subparsers.add_parser(
        "describe-control-catalog",
        help="Describe static control points, instruction sources, and workflow branches",
        parents=[common],
    )
    describe_control_catalog.set_defaults(func=_cmd_describe_control_catalog)

    plan = subparsers.add_parser("plan", help="Create an execution plan for a case", parents=[common])
    plan.add_argument("prompt", help="User request for planning")
    plan.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    plan.add_argument("--external-ticket-id", default=None, help="Explicit external ticket ID. If omitted, external ticket lookup is skipped")
    plan.add_argument("--internal-ticket-id", default=None, help="Explicit internal ticket ID. If omitted, internal ticket lookup is skipped")
    plan.set_defaults(func=_cmd_plan)

    action = subparsers.add_parser("action", help="Execute action mode for a case", parents=[common])
    action.add_argument("prompt", help="User request for action execution")
    action.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    action.add_argument("--trace-id", default=None, help="Trace identifier from plan mode")
    action.add_argument("--execution-plan", default=None, help="Optional execution plan text")
    action.add_argument("--external-ticket-id", default=None, help="Explicit external ticket ID. If omitted, external ticket lookup is skipped")
    action.add_argument("--internal-ticket-id", default=None, help="Explicit internal ticket ID. If omitted, internal ticket lookup is skipped")
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
        help="Export semi-automatic per-tool docs drafts from ToolRegistry",
        parents=[common],
    )
    export_tool_docs.add_argument(
        "--output-dir",
        default="docs/tools/generated",
        help="Directory where generated per-tool markdown drafts are written",
    )
    export_tool_docs.set_defaults(func=_cmd_export_tool_docs)

    generate_report = subparsers.add_parser(
        "generate-report",
        help="Generate a support improvement evaluation report into the report directory",
        parents=[common],
    )
    generate_report.add_argument("--case-id", required=True, help="Case identifier")
    generate_report.add_argument("--trace-id", required=True, help="Trace identifier")
    generate_report.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    generate_report.add_argument(
        "--checklist",
        action="append",
        default=None,
        help="Optional checklist item to include in the report. Can be passed multiple times.",
    )
    generate_report.set_defaults(func=_cmd_generate_report)

    checkpoint_status = subparsers.add_parser(
        "checkpoint-status",
        help="Show workspace-local SQLite checkpoint DB status and trace IDs",
        parents=[common],
    )
    checkpoint_status.add_argument("--case-id", required=True, help="Case identifier")
    checkpoint_status.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    checkpoint_status.add_argument("--trace-id", default=None, help="Optional trace identifier to inspect")
    checkpoint_status.add_argument("--limit", type=int, default=20, help="Maximum number of trace IDs to list")
    checkpoint_status.set_defaults(func=_cmd_checkpoint_status)

    evaluate_investigate = subparsers.add_parser(
        "evaluate-investigate",
        help="Run Sample InvestigateAgent standalone and evaluate the answer quality",
        parents=[common],
    )
    evaluate_investigate.add_argument("prompt", help="Investigation prompt to run")
    evaluate_investigate.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    evaluate_investigate.add_argument("--case-id", default=None, help="Optional case identifier override")
    evaluate_investigate.add_argument(
        "--checklist-template",
        choices=sorted(INVESTIGATE_CHECKLIST_TEMPLATES.keys()),
        default=None,
        help="Optional built-in checklist template to preload for evaluation.",
    )
    evaluate_investigate.add_argument(
        "--checklist",
        action="append",
        default=None,
        help="Optional evaluation checklist item. Can be passed multiple times.",
    )
    evaluate_investigate.add_argument(
        "--output",
        default=None,
        help="Optional path to save the evaluation result JSON.",
    )
    evaluate_investigate.set_defaults(func=_cmd_evaluate_investigate)

    run_sample_supervisor = subparsers.add_parser(
        "run-sample-supervisor",
        help="Run Sample SuperVisorAgent from a workspace and return the resulting state",
        parents=[common],
    )
    run_sample_supervisor.add_argument("prompt", help="User request to start the supervisor investigation flow")
    run_sample_supervisor.add_argument("--workspace-path", required=True, help="Workspace path for the case")
    run_sample_supervisor.add_argument("--case-id", default=None, help="Optional case identifier override")
    run_sample_supervisor.add_argument(
        "--output",
        default=None,
        help="Optional path to save the supervisor result JSON.",
    )
    run_sample_supervisor.set_defaults(func=_cmd_run_sample_supervisor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())