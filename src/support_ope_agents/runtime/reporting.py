from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, cast

from support_ope_agents.agents.objective_evaluation_agent import ObjectiveEvaluationAgent
from support_ope_agents.agents.roles import OBJECTIVE_EVALUATION_AGENT
from support_ope_agents.config.models import AppConfig
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
from support_ope_agents.workflow.case_workflow import reconstruct_main_workflow_path
from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class EvaluationReportResult:
    report_path: Path
    sequence_diagram: str
    content: str


@dataclass(slots=True)
class AgentEvaluation:
    agent_name: str
    score: int
    is_good: bool
    detail: str
    improvement_point: str | None = None
    evidence: list[str] = field(default_factory=list)
    critical_failure: bool = False


@dataclass(slots=True)
class MemoryConsistencyFinding:
    agent_name: str
    severity: str
    detail: str


@dataclass(slots=True)
class SubgraphSequenceDiagram:
    title: str
    diagram: str


@dataclass(slots=True)
class CriterionEvaluation:
    name: str
    viewpoint: str
    result: str
    score: int
    criterion_key: str | None = None
    related_checklist_items: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class InstructionCriterion:
    key: str
    title: str
    viewpoint: str
    improvement_hint: str


@dataclass(slots=True)
class ObjectiveEvaluation:
    evaluator_name: str
    instruction_excerpt: str
    sequence_diagram: str
    subgraph_sequence_diagrams: list[SubgraphSequenceDiagram]
    criterion_evaluations: list[CriterionEvaluation]
    agent_evaluations: list[AgentEvaluation]
    memory_findings: list[MemoryConsistencyFinding]
    overall_summary: str
    improvement_points: list[str]
    score: int


def build_support_improvement_report(
    *,
    case_id: str,
    trace_id: str,
    workspace_path: str,
    state: CaseState,
    memory_store: CaseMemoryStore,
    instruction_loader: InstructionLoader,
    config: AppConfig,
    control_catalog: dict[str, object] | None = None,
    runtime_audit: dict[str, object] | None = None,
    checklist: list[str] | None = None,
) -> EvaluationReportResult:
    case_paths = memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
    context_text = memory_store.read_text(case_paths.shared_context)
    progress_text = memory_store.read_text(case_paths.shared_progress)
    summary_text = memory_store.read_text(case_paths.shared_summary)
    artifact_paths = [path.relative_to(case_paths.root).as_posix() for path in memory_store.list_artifacts(case_id, workspace_path)]

    evaluator_instruction = instruction_loader.load(case_id, OBJECTIVE_EVALUATION_AGENT)
    shared_memory = {
        "context": context_text,
        "progress": progress_text,
        "summary": summary_text,
    }
    runtime_audit_payload = runtime_audit or {}
    control_catalog_payload = control_catalog or {}
    agent_memories = _load_agent_memories(case_paths, memory_store)
    memory_findings = _audit_memory_consistency(state, shared_memory, agent_memories)
    normalized_checklist = _normalize_checklist(checklist or [])
    instruction_criteria = _extract_instruction_criteria(evaluator_instruction, normalized_checklist)
    structured_evaluation = ObjectiveEvaluationAgent(config=config, instruction_text=evaluator_instruction).evaluate(
        evidence=_build_objective_evaluation_evidence(
            case_id=case_id,
            trace_id=trace_id,
            state=state,
            shared_memory=shared_memory,
            agent_memories=agent_memories,
            memory_findings=memory_findings,
            artifact_paths=artifact_paths,
            checklist=normalized_checklist,
            expected_criteria=instruction_criteria,
        )
    )
    evaluation = _build_objective_evaluation(
        state=state,
        instruction_text=evaluator_instruction,
        shared_memory=shared_memory,
        memory_findings=memory_findings,
        structured_evaluation=structured_evaluation,
        pass_score=config.agents.ObjectiveEvaluationAgent.pass_score,
        checklist=normalized_checklist,
        checklist_assessments=_assess_checklist_items(
            normalized_checklist,
            state,
            context_text,
            progress_text,
            summary_text,
        ),
        instruction_criteria=instruction_criteria,
        runtime_audit=runtime_audit_payload,
        control_catalog=control_catalog_payload,
    )
    checklist_section = _render_checklist(evaluation.criterion_evaluations, normalized_checklist)
    control_summary_section = _render_control_summary(control_catalog_payload, runtime_audit_payload)
    control_catalog_section = _render_control_catalog_section(control_catalog_payload, runtime_audit_payload)
    runtime_constraints_section = _render_runtime_constraints(runtime_audit_payload)
    runtime_policies_section = _render_runtime_policies(runtime_audit_payload)
    runtime_policy_effects_section = _render_runtime_policy_effects(runtime_audit_payload)

    report_lines = [
        f"# Support Improvement Report: {case_id}",
        "",
        "## Meta",
        *_report_item("Case ID", case_id, "レポート対象のケースを一意に識別するIDです。"),
        *_report_item("Trace ID", trace_id, "今回の実行トレースを追跡するための識別子です。"),
        *_report_item("Workspace", case_paths.root, "ケース関連ファイルと成果物を保存した作業ディレクトリです。"),
        *_report_item("Final status", str(state.get("status") or "unknown"), "ワークフロー完了時点の最終ステータスです。"),
        *_report_item("Evaluator", evaluation.evaluator_name, "SuperVisor ではなく、instruction と structured output schema に基づいて評価する客観評価エージェントです。"),
        *_report_item("Evaluation rubric", evaluation.instruction_excerpt or "n/a", "Evaluator instruction の冒頭要約です。"),
        "",
        "## 問い合わせ内容",
        "問い合わせ原文または整形後の主訴です。調査対象の起点として参照します。",
        str(state.get("raw_issue") or "n/a"),
        "",
        "## 回答内容",
        "サポート担当者に返却した、または返却予定の調査回答本文です。",
        str(state.get("draft_response") or state.get("escalation_draft") or "n/a"),
        "",
        "## 調査に使用したログ・成果物",
        "調査時に参照した添付ファイル、ログ、派生成果物の一覧です。",
        *([f"- {path}" for path in artifact_paths] or ["- なし"]),
        "",
        "## 結果と評価",
        *_report_item("結果", _result_label(state), "最終的に確定した対応方針を示します。"),
        *_report_item("調査要約", str(state.get("investigation_summary") or "n/a"), "ログ解析やナレッジ確認を踏まえた調査結果の要約です。"),
        *_report_item("コンプライアンス要約", str(state.get("compliance_review_summary") or "n/a"), "回答案に対するレビュー観点と判定結果の要約です。"),
        *_report_item("エスカレーション理由", str(state.get("escalation_reason") or "n/a"), "追加確認や上位支援が必要と判断した根拠です。"),
        "",
        "## 制御サマリー",
        "定義済みの制御点と、この trace で実際に発火した制御をまとめます。",
        *control_summary_section,
        "",
        "## 制御一覧",
        "定義済みの制御点を一覧化します。active はこの trace で発火した制御です。",
        *control_catalog_section,
        "",
        "## ランタイム制約一覧",
        "RuntimeHarnessManager が role ごとに解決した runtime 制約の有効状態です。",
        *runtime_constraints_section,
        "",
        "## ランタイム制約ポリシー一覧",
        "RuntimeHarnessManager が今回の trace に対して解決した実効 policy 値です。",
        *runtime_policies_section,
        "",
        "## ランタイム制約影響評価",
        "今回の trace から deterministic に評価できる runtime 制約の影響です。",
        *runtime_policy_effects_section,
        "",
        "## コンプライアンスレビュー履歴",
        "各レビュー周回での指摘内容と、その時点の対応内容を時系列で示します。",
        *_render_compliance_review_history(cast(list[dict[str, object]], state.get("compliance_review_history") or [])),
        "",
        "## Evaluator 評価観点一覧",
        "ObjectiveEvaluationAgent が instruction に基づいて出力した評価観点一覧と、その結果です。",
        *_render_criterion_evaluations(evaluation.criterion_evaluations),
        "",
        "## 総合評価",
        "### 総評",
        "ケース全体を通した自動対応品質の総括です。ObjectiveEvaluationAgent が instruction と structured output で判定しています。",
        evaluation.overall_summary,
        "",
        "### 要改善点",
        "各エージェントや処理全体の課題、改善点を一覧化します。",
        *([f"- {item}" for item in evaluation.improvement_points] or ["- なし"]),
        "",
        "### 点数",
        "0～100で評価します。",
        f"{evaluation.score} / 100",
        "",
        "## エージェント呼び出しシーケンス",
        "問い合わせ受付から回答またはエスカレーションまでの呼び出し順を図示します。",
        "```mermaid",
        evaluation.sequence_diagram,
        "```",
        "",
        "## サブグラフ詳細シーケンス",
        "IntakeAgent など内部フェーズを持つエージェントについて、サブグラフ単位の詳細シーケンスを併記します。",
        *_render_subgraph_sequence_section(evaluation.subgraph_sequence_diagrams),
        "",
        "## エージェント別評価",
        "各エージェントの役割ごとに、出力の有無、メモリ連携、品質を点数付きで評価した一覧です。",
        *[f"- {_format_agent_evaluation(item)}" for item in evaluation.agent_evaluations],
        "",
        "## 情報伝達監査",
        ".memory/shared と各エージェント working memory を照合し、情報欠落リスクを確認します。",
        *([f"- {_format_memory_finding(item)}" for item in evaluation.memory_findings] or ["- 重大な欠落リスクは検出されませんでした"]),
        "",
        "## ユーザー指定チェックリスト",
        "ユーザーが確認したい観点について、出力本文や共有メモリとの一致状況を示します。",
        *checklist_section,
        "",
        "## Shared Memory Snapshot",
        "### Context",
        "ケースの背景、前提条件、固定情報などの共有コンテキストです。",
        context_text.strip() or "n/a",
        "",
        "### Progress",
        "途中経過や実施済みアクションを記録した進捗メモです。",
        progress_text.strip() or "n/a",
        "",
        "### Summary",
        "主要判断や最終要点を簡潔にまとめた共有サマリーです。",
        summary_text.strip() or "n/a",
        "",
    ]
    content = "\n".join(report_lines)
    report_path = case_paths.report_dir / f"support-improvement-{trace_id}.md"
    report_path.write_text(content, encoding="utf-8")
    return EvaluationReportResult(report_path=report_path, sequence_diagram=evaluation.sequence_diagram, content=content)


def _render_control_summary(control_catalog: dict[str, object], runtime_audit: dict[str, object]) -> list[str]:
    if not control_catalog and not runtime_audit:
        return ["- なし"]

    lines: list[str] = []
    summary = control_catalog.get("summary") if isinstance(control_catalog, dict) else None
    if isinstance(summary, dict):
        lines.extend(
            [
                "### 定義済み制御の規模",
                f"- Control points: {summary.get('control_point_count', 0)}",
                f"- Agents: {summary.get('agent_count', 0)}",
                f"- Workflow nodes: {summary.get('workflow_node_count', 0)}",
                f"- Logical tools: {summary.get('logical_tool_count', 0)}",
                "",
            ]
        )

    audit_summary = runtime_audit.get("summary") if isinstance(runtime_audit, dict) else None
    if isinstance(audit_summary, dict):
        lines.extend(
            [
                "### 実行時監査",
                f"- Trace ID: {audit_summary.get('trace_id', 'n/a')}",
                f"- Status: {audit_summary.get('status', 'n/a')}",
                f"- Workflow kind: {audit_summary.get('workflow_kind', 'n/a')}",
                f"- Result: {audit_summary.get('result', 'n/a')}",
                f"- Approval route: {audit_summary.get('approval_route', 'n/a')}",
            ]
        )
    workflow_path = runtime_audit.get("workflow_path") if isinstance(runtime_audit, dict) else None
    if isinstance(workflow_path, list):
        lines.append(f"- Workflow path: {' -> '.join(str(item) for item in workflow_path)}")

    used_roles = runtime_audit.get("used_roles") if isinstance(runtime_audit, dict) else None
    if isinstance(used_roles, list):
        lines.append(f"- Used roles: {', '.join(str(item) for item in used_roles) if used_roles else 'なし'}")

    decision_log = runtime_audit.get("decision_log") if isinstance(runtime_audit, dict) else None
    if isinstance(decision_log, list):
        lines.extend(["", "### 発火した制御"])
        if not decision_log:
            lines.append("- なし")
        else:
            for item in decision_log:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- [{str(item.get('category') or 'unknown')}] {str(item.get('control_point_id') or 'n/a')}: {str(item.get('detail') or '')}"
                )

    instruction_resolution = runtime_audit.get("instruction_resolution") if isinstance(runtime_audit, dict) else None
    if isinstance(instruction_resolution, list):
        lines.extend(["", "### 解決された instruction"])
        if not instruction_resolution:
            lines.append("- なし")
        else:
            common_instruction_constraints = runtime_audit.get("common_instruction_constraints") if isinstance(runtime_audit, dict) else None
            if isinstance(common_instruction_constraints, list) and common_instruction_constraints:
                lines.append("- 共通 instruction 制約:")
                for constraint in common_instruction_constraints:
                    lines.append(f"  - {str(constraint)}")
            for item in instruction_resolution:
                if not isinstance(item, dict):
                    continue
                sources = item.get("resolved_sources")
                source_count = len(sources) if isinstance(sources, list) else 0
                lines.append(
                    f"- {str(item.get('role') or 'unknown')}: {source_count} source(s) resolved"
                )
                inferred_constraints = item.get("inferred_constraints")
                if isinstance(inferred_constraints, list) and inferred_constraints:
                    lines.append("  - 役割別の想定 instruction 制約:")
                    for constraint in inferred_constraints:
                        lines.append(f"    - {str(constraint)}")
    return lines or ["- なし"]


def _render_control_catalog_section(control_catalog: dict[str, object], runtime_audit: dict[str, object]) -> list[str]:
    control_points = control_catalog.get("control_points") if isinstance(control_catalog, dict) else None
    if not isinstance(control_points, list) or not control_points:
        return ["- なし"]

    active_ids_raw = runtime_audit.get("active_control_point_ids") if isinstance(runtime_audit, dict) else None
    active_ids = {
        str(item).strip()
        for item in active_ids_raw
        if str(item).strip()
    } if isinstance(active_ids_raw, list) else set()

    lines: list[str] = []
    for item in control_points:
        if not isinstance(item, dict):
            continue
        control_point_id = str(item.get("id") or "n/a")
        marker = "active" if control_point_id in active_ids else "defined"
        category = str(item.get("category") or "unknown")
        owner = str(item.get("owner") or "unknown")
        origin = str(item.get("origin") or "unknown")
        condition = str(item.get("condition") or "always")
        effect = str(item.get("effect") or "")
        lines.append(f"- [{marker}] {control_point_id} ({category})")
        lines.append(f"  owner: {owner}")
        lines.append(f"  origin: {origin}")
        lines.append(f"  condition: {condition}")
        if effect:
            lines.append(f"  effect: {effect}")
        config_key = str(item.get("config_key") or "").strip()
        if config_key:
            lines.append(f"  config_key: {config_key}")
        docs_refs = item.get("docs_refs")
        if isinstance(docs_refs, list):
            normalized_docs = [str(ref).strip() for ref in docs_refs if str(ref).strip()]
            if normalized_docs:
                lines.append(f"  docs_refs: {', '.join(normalized_docs)}")
        code_refs = item.get("code_refs")
        if isinstance(code_refs, list):
            normalized_code = [str(ref).strip() for ref in code_refs if str(ref).strip()]
            if normalized_code:
                lines.append(f"  code_refs: {', '.join(normalized_code)}")
    return lines or ["- なし"]


def _render_runtime_constraints(runtime_audit: dict[str, object]) -> list[str]:
    runtime_constraints = runtime_audit.get("runtime_constraints") if isinstance(runtime_audit, dict) else None
    if not isinstance(runtime_constraints, list) or not runtime_constraints:
        return ["- なし"]

    lines: list[str] = []
    for item in runtime_constraints:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "unknown")
        constraint_mode = str(item.get("constraint_mode") or "unknown")
        instruction_enabled = "yes" if bool(item.get("instruction_enabled")) else "no"
        runtime_enabled = "yes" if bool(item.get("runtime_enabled")) else "no"
        summary_enabled = "yes" if bool(item.get("summary_constraints_enabled")) else "no"
        lines.append(
            f"- {role}: mode={constraint_mode}, instruction={instruction_enabled}, runtime={runtime_enabled}, summary={summary_enabled}"
        )
    return lines or ["- なし"]


def _render_runtime_policies(runtime_audit: dict[str, object]) -> list[str]:
    runtime_policies = runtime_audit.get("runtime_policies") if isinstance(runtime_audit, dict) else None
    if not isinstance(runtime_policies, dict):
        return ["- なし"]

    lines: list[str] = []
    global_policies = runtime_policies.get("global_policies")
    if isinstance(global_policies, list) and global_policies:
        lines.append("### Global policies")
        for item in global_policies:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('policy_id') or 'unknown')}: value={item.get('value')}, source={str(item.get('source') or 'unknown')}"
            )

    role_policies = runtime_policies.get("role_policies")
    if isinstance(role_policies, list) and role_policies:
        for role_entry in role_policies:
            if not isinstance(role_entry, dict):
                continue
            role = str(role_entry.get("role") or "unknown")
            policies = role_entry.get("policies")
            lines.append(f"### {role}")
            if not isinstance(policies, list) or not policies:
                lines.append("- policy なし")
                continue
            for policy in policies:
                if not isinstance(policy, dict):
                    continue
                lines.append(
                    f"- {str(policy.get('policy_id') or 'unknown')}: value={policy.get('value')}, source={str(policy.get('source') or 'unknown')}"
                )

    return lines or ["- なし"]


def _render_runtime_policy_effects(runtime_audit: dict[str, object]) -> list[str]:
    effects = runtime_audit.get("runtime_policy_effects") if isinstance(runtime_audit, dict) else None
    if not isinstance(effects, list) or not effects:
        return ["- なし"]

    lines: list[str] = []
    for item in effects:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner") or "unknown")
        policy_id = str(item.get("policy_id") or "unknown")
        impact_level = str(item.get("impact_level") or "configured")
        observable_output = str(item.get("observable_output") or "n/a")
        effect_summary = str(item.get("effect_summary") or "")
        lines.append(
            f"- {owner}.{policy_id} [{impact_level}]: {effect_summary} | observed={observable_output}"
        )
    return lines or ["- なし"]


def _build_objective_evaluation_evidence(
    *,
    case_id: str,
    trace_id: str,
    state: CaseState,
    shared_memory: dict[str, str],
    agent_memories: dict[str, str],
    memory_findings: list[MemoryConsistencyFinding],
    artifact_paths: list[str],
    checklist: list[str],
    expected_criteria: list[InstructionCriterion],
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "trace_id": trace_id,
        "status": str(state.get("status") or "unknown"),
        "workflow_kind": _effective_workflow_kind(state),
        "raw_issue": str(state.get("raw_issue") or ""),
        "draft_response": str(state.get("draft_response") or ""),
        "investigation_summary": str(state.get("investigation_summary") or ""),
        "compliance_review_summary": str(state.get("compliance_review_summary") or ""),
        "compliance_review_history": list(state.get("compliance_review_history") or []),
        "escalation_reason": str(state.get("escalation_reason") or ""),
        "escalation_summary": str(state.get("escalation_summary") or ""),
        "escalation_draft": str(state.get("escalation_draft") or ""),
        "log_analysis_summary": str(state.get("log_analysis_summary") or ""),
        "knowledge_retrieval_adopted_sources": list(state.get("knowledge_retrieval_adopted_sources") or []),
        "shared_memory": shared_memory,
        "agent_memories": agent_memories,
        "memory_findings": [
            {"agent_name": item.agent_name, "severity": item.severity, "detail": item.detail}
            for item in memory_findings
        ],
        "artifact_paths": artifact_paths,
        "user_checklist": checklist,
        "expected_criteria": [
            {
                "criterion_key": item.key,
                "title": item.title,
                "viewpoint": item.viewpoint,
                "improvement_hint": item.improvement_hint,
            }
            for item in expected_criteria
        ],
        "agent_errors": list(state.get("agent_errors") or []),
    }


def _build_objective_evaluation(
    *,
    state: CaseState,
    instruction_text: str,
    shared_memory: dict[str, str],
    memory_findings: list[MemoryConsistencyFinding],
    structured_evaluation: Any,
    pass_score: int,
    checklist: list[str],
    checklist_assessments: list[tuple[str, str]],
    instruction_criteria: list[InstructionCriterion],
    runtime_audit: dict[str, object],
    control_catalog: dict[str, object],
) -> ObjectiveEvaluation:
    criterion_evaluations = [
        CriterionEvaluation(
            criterion_key=getattr(item, "criterion_key", None),
            name=item.title,
            viewpoint=item.viewpoint,
            result=item.result,
            score=item.score,
            related_checklist_items=list(getattr(item, "related_checklist_items", []) or []),
        )
        for item in structured_evaluation.criterion_evaluations
    ]
    criterion_evaluations = _merge_missing_instruction_criteria(criterion_evaluations, instruction_criteria)
    criterion_evaluations = _merge_missing_checklist_criteria(criterion_evaluations, checklist_assessments)
    agent_evaluations = [
        AgentEvaluation(
            agent_name=item.agent_name,
            score=item.score,
            is_good=item.score >= pass_score,
            detail=item.comment,
        )
        for item in structured_evaluation.agent_evaluations
    ]
    criterion_evaluations = _postprocess_criterion_evaluations(
        criterion_evaluations,
        state=state,
        shared_memory=shared_memory,
        memory_findings=memory_findings,
    )
    improvement_points = _sanitize_improvement_points(
        _merge_instruction_improvement_points(
            _merge_checklist_improvement_points(
                list(structured_evaluation.improvement_points),
                checklist_assessments,
            ),
            criterion_evaluations,
            instruction_criteria,
        ),
        state=state,
        shared_memory=shared_memory,
        memory_findings=memory_findings,
    )
    return ObjectiveEvaluation(
        evaluator_name=OBJECTIVE_EVALUATION_AGENT,
        instruction_excerpt=_instruction_excerpt(instruction_text),
        sequence_diagram=_build_sequence_diagram(state, runtime_audit=runtime_audit, control_catalog=control_catalog),
        subgraph_sequence_diagrams=_build_subgraph_sequence_diagrams(
            state,
            runtime_audit=runtime_audit,
            control_catalog=control_catalog,
        ),
        criterion_evaluations=criterion_evaluations,
        agent_evaluations=agent_evaluations,
        memory_findings=memory_findings,
        overall_summary=_sanitize_overall_summary(
            str(structured_evaluation.overall_summary or ""),
            shared_memory=shared_memory,
        ),
        improvement_points=improvement_points,
        score=structured_evaluation.overall_score,
    )


def _result_label(state: CaseState) -> str:
    if bool(state.get("escalation_required")):
        return "エスカレーションが必要だった"
    if bool(state.get("compliance_review_passed")):
        return "確実な回答が得られた"
    return "回答ドラフトは作成されたが追加確認が必要"


def _effective_workflow_kind(state: CaseState) -> str:
    workflow_kind = str(state.get("workflow_kind") or "").strip()
    intake_category = str(state.get("intake_category") or "").strip()
    valid_values = {"specification_inquiry", "incident_investigation", "ambiguous_case"}
    if workflow_kind not in valid_values:
        return intake_category if intake_category in valid_values else "ambiguous_case"
    if workflow_kind == "ambiguous_case" and intake_category in {"specification_inquiry", "incident_investigation"}:
        return intake_category
    return workflow_kind


def _build_sequence_diagram(
    state: CaseState,
    *,
    runtime_audit: dict[str, object] | None = None,
    control_catalog: dict[str, object] | None = None,
) -> str:
    path = _workflow_path_for_report(state, runtime_audit)
    approval_route = _approval_route_for_report(state, runtime_audit)
    participants = _sequence_participants(path, runtime_audit)
    lines = [
        "sequenceDiagram",
    ]
    lines.extend([f"    participant {name} as {label}" for name, label in participants])
    if _has_participant(participants, "User") and _has_participant(participants, "Intake"):
        lines.append("    User->>Intake: 問い合わせ入力")
    if _has_participant(participants, "Intake") and _has_participant(participants, "Supervisor"):
        lines.append("    Intake->>Supervisor: Intake 結果を引き渡し")
    if "wait_for_customer_input" in path:
        lines.append("    Intake-->>User: 追加情報を依頼")
        return "\n".join(lines)

    if _has_participant(participants, "LogAnalyzer"):
        lines.append("    Supervisor->>LogAnalyzer: ログ解析を依頼")
        lines.append("    LogAnalyzer-->>Supervisor: ログ解析結果を返却")
    if _has_participant(participants, "Knowledge"):
        lines.append("    Supervisor->>Knowledge: ナレッジ検索を依頼")
        lines.append("    Knowledge-->>Supervisor: 検索結果を返却")

    if "escalation_review" in path:
        lines.append("    Supervisor->>Escalation: エスカレーション判断と要約を依頼")
        lines.append("    Escalation-->>Supervisor: エスカレーション要約を返却")
        lines.append("    Supervisor->>Inquiry: 問い合わせ文案作成を依頼")
        lines.append("    Inquiry-->>Supervisor: エスカレーション文案を返却")
        lines.append("    Supervisor->>Approval: 承認依頼を送信")
        if approval_route == "investigation":
            lines.append("    Approval->>Supervisor: 再調査を依頼")
        elif approval_route == "draft_review":
            lines.append("    Approval->>Supervisor: 差戻しを依頼")
            lines.append("    Supervisor->>Inquiry: 問い合わせ文案の修正を依頼")
        elif approval_route == "ticket_update_prepare":
            lines.append("    Approval->>TicketUpdate: 承認済み更新を依頼")
            lines.append("    TicketUpdate-->>User: 更新完了")
    elif "draft_review" in path:
        lines.append("    Supervisor->>DraftWriter: 回答ドラフト作成を依頼")
        review_iterations = sum(1 for node in path if node == "draft_review")
        for _ in range(max(1, review_iterations)):
            lines.append("    DraftWriter-->>Supervisor: ドラフトを返却")
            lines.append("    Supervisor->>Compliance: コンプライアンス確認を依頼")
            lines.append("    Compliance-->>Supervisor: レビュー結果を返却")
        lines.append("    Supervisor->>Approval: 承認依頼を送信")
        if approval_route == "investigation":
            lines.append("    Approval->>Supervisor: 再調査を依頼")
        elif approval_route == "draft_review":
            lines.append("    Approval->>Supervisor: 差戻しを依頼")
            lines.append("    Supervisor->>DraftWriter: 修正版ドラフト作成を依頼")
        elif approval_route == "ticket_update_prepare":
            lines.append("    Approval->>TicketUpdate: 承認済み更新を依頼")
            lines.append("    TicketUpdate-->>User: 更新完了")
    return "\n".join(lines)


def _approval_route_for_report(state: CaseState, runtime_audit: dict[str, object] | None = None) -> str:
    audit_summary = runtime_audit.get("summary") if isinstance(runtime_audit, dict) else None
    if isinstance(audit_summary, dict):
        route = str(audit_summary.get("approval_route") or "").strip()
        if route:
            return route
    if str(state.get("status") or "") == "CLOSED" or str(state.get("ticket_update_result") or "").strip():
        return "ticket_update_prepare"
    decision = str(state.get("approval_decision") or "").strip().lower()
    if decision in {"approved", "approve"}:
        return "ticket_update_prepare"
    if decision in {"rejected", "reject"}:
        return "draft_review"
    if decision == "reinvestigate":
        return "investigation"
    return "__end__"


def _workflow_path_for_report(state: CaseState, runtime_audit: dict[str, object] | None) -> tuple[str, ...]:
    workflow_path = runtime_audit.get("workflow_path") if isinstance(runtime_audit, dict) else None
    if isinstance(workflow_path, list) and workflow_path:
        return tuple(str(item) for item in workflow_path if str(item).strip())
    return reconstruct_main_workflow_path(state)


def _sequence_participants(
    workflow_path: tuple[str, ...],
    runtime_audit: dict[str, object] | None,
) -> list[tuple[str, str]]:
    participant_defs = [
        ("User", "User"),
        ("Intake", "IntakeAgent"),
        ("Supervisor", "SuperVisorAgent"),
        ("LogAnalyzer", "LogAnalyzerAgent"),
        ("Knowledge", "KnowledgeRetrieverAgent"),
        ("DraftWriter", "DraftWriterAgent"),
        ("Compliance", "ComplianceReviewerAgent"),
        ("Approval", "ApprovalAgent"),
        ("TicketUpdate", "TicketUpdateAgent"),
        ("Escalation", "BackSupportEscalationAgent"),
        ("Inquiry", "BackSupportInquiryWriterAgent"),
    ]
    used_roles = runtime_audit.get("used_roles") if isinstance(runtime_audit, dict) else None
    used_role_set = {str(item) for item in used_roles} if isinstance(used_roles, list) else set()
    included: list[tuple[str, str]] = []
    for alias, label in participant_defs:
        if alias == "User":
            included.append((alias, label))
            continue
        if label in used_role_set:
            included.append((alias, label))
            continue
        if alias == "Intake" and any(node.startswith("intake_") or node == "wait_for_customer_input" for node in workflow_path):
            included.append((alias, label))
        elif alias == "Supervisor" and any(node in {"investigation", "draft_review", "escalation_review", "wait_for_approval", "ticket_update_prepare"} for node in workflow_path):
            included.append((alias, label))
        elif alias == "DraftWriter" and "draft_review" in workflow_path:
            included.append((alias, label))
        elif alias == "Compliance" and "draft_review" in workflow_path:
            included.append((alias, label))
        elif alias == "Approval" and "wait_for_approval" in workflow_path:
            included.append((alias, label))
        elif alias == "TicketUpdate" and "ticket_update_prepare" in workflow_path:
            included.append((alias, label))
        elif alias == "Escalation" and "escalation_review" in workflow_path:
            included.append((alias, label))
        elif alias == "Inquiry" and "escalation_review" in workflow_path:
            included.append((alias, label))
    return included


def _has_participant(participants: list[tuple[str, str]], alias: str) -> bool:
    return any(name == alias for name, _ in participants)


def _build_subgraph_sequence_diagrams(
    state: CaseState,
    *,
    runtime_audit: dict[str, object] | None = None,
    control_catalog: dict[str, object] | None = None,
) -> list[SubgraphSequenceDiagram]:
    del control_catalog
    path = _workflow_path_for_report(state, runtime_audit)
    approval_route = _approval_route_for_report(state, runtime_audit)
    intake_lines = [
        "sequenceDiagram",
        "    participant User as User",
        "    participant Intake as IntakeAgent",
        "    participant Prepare as intake_prepare",
        "    participant Mask as intake_mask",
        "    participant Hydrate as intake_hydrate_tickets",
        "    participant Classify as intake_classify",
        "    participant Finalize as intake_finalize",
        "    User->>Intake: 問い合わせ入力",
        "    Intake->>Prepare: 初期状態を準備",
        "    Prepare->>Mask: PII マスキング",
        "    Mask->>Hydrate: チケット文脈を補完",
        "    Hydrate->>Classify: 問い合わせ分類",
        "    Classify->>Finalize: 次フェーズを決定",
    ]
    if "wait_for_customer_input" in path:
        intake_lines.append("    Finalize-->>User: 追加情報を依頼")
    elif "investigation" in path:
        intake_lines.append("    Finalize->>Supervisor: 調査フェーズへ引き継ぎ")

    diagrams = [
        SubgraphSequenceDiagram(
            title="IntakeAgent サブグラフ",
            diagram="\n".join(intake_lines),
        )
    ]
    if "draft_review" in path:
        review_iterations = sum(1 for node in path if node == "draft_review")
        review_lines = [
            "sequenceDiagram",
            "    participant Supervisor as SuperVisorAgent",
            "    participant DraftWriter as DraftWriterAgent",
            "    participant Compliance as ComplianceReviewerAgent",
            "    participant Approval as ApprovalAgent",
            "    Supervisor->>DraftWriter: 回答ドラフト作成を依頼",
        ]
        for index in range(max(1, review_iterations)):
            review_lines.append(f"    DraftWriter-->>Supervisor: ドラフトを返却 ({index + 1})")
            review_lines.append(f"    Supervisor->>Compliance: レビュー依頼 ({index + 1})")
            review_lines.append(f"    Compliance-->>Supervisor: レビュー結果を返却 ({index + 1})")
        if approval_route == "draft_review":
            review_lines.append("    Approval->>Supervisor: 差戻し判断を返却")
        elif approval_route == "investigation":
            review_lines.append("    Approval->>Supervisor: 再調査判断を返却")
        diagrams.append(
            SubgraphSequenceDiagram(
                title="Draft Review ループ",
                diagram="\n".join(review_lines),
            )
        )
    if "escalation_review" in path:
        escalation_lines = [
            "sequenceDiagram",
            "    participant Supervisor as SuperVisorAgent",
            "    participant Escalation as BackSupportEscalationAgent",
            "    participant Inquiry as BackSupportInquiryWriterAgent",
            "    participant Approval as ApprovalAgent",
            "    Supervisor->>Escalation: 判断根拠と不足情報を整理",
            "    Escalation-->>Supervisor: エスカレーション要約を返却",
            "    Supervisor->>Inquiry: バックサポート向け問い合わせ文案を依頼",
            "    Inquiry-->>Supervisor: 問い合わせ文案を返却",
            "    Supervisor->>Approval: 承認待ちへ回付",
        ]
        if approval_route == "investigation":
            escalation_lines.append("    Approval->>Supervisor: 再調査判断を返却")
        elif approval_route == "draft_review":
            escalation_lines.append("    Approval->>Supervisor: 文案差戻しを返却")
            escalation_lines.append("    Supervisor->>Inquiry: 修正版問い合わせ文案を依頼")
        diagrams.append(
            SubgraphSequenceDiagram(
                title="Escalation 準備フロー",
                diagram="\n".join(escalation_lines),
            )
        )
    if "ticket_update_prepare" in path:
        diagrams.append(
            SubgraphSequenceDiagram(
                title="TicketUpdateAgent サブグラフ",
                diagram="\n".join([
                    "sequenceDiagram",
                    "    participant Approval as ApprovalAgent",
                    "    participant TicketUpdate as TicketUpdateAgent",
                    "    participant Prepare as ticket_update_prepare",
                    "    participant Execute as ticket_update_execute",
                    "    participant User as User",
                    "    Approval->>TicketUpdate: 更新を承認",
                    "    TicketUpdate->>Prepare: 更新 payload を準備",
                    "    Prepare->>Execute: 外部チケットを更新",
                    "    Execute-->>User: 更新結果を通知",
                ]),
            )
        )
    return diagrams


def _normalize_checklist(checklist: list[str]) -> list[str]:
    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in checklist:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_items.append(normalized)
    return normalized_items


def _extract_instruction_criteria(instruction_text: str, checklist: list[str]) -> list[InstructionCriterion]:
    bullets = _extract_markdown_bullets(instruction_text, "## 評価方針")
    criteria: list[InstructionCriterion] = []
    for bullet in bullets:
        normalized = re.sub(r"\s+", " ", bullet).strip()
        if not normalized:
            continue
        if "ユーザーが何を知りたいか" in normalized or "質問内容を確認" in normalized:
            criteria.append(
                InstructionCriterion(
                    key="question_intent",
                    title="質問意図の理解と回答妥当性",
                    viewpoint="ユーザーが何を知りたいかを解釈し、回答が結論・原因・次アクションまで十分に返せているかを確認する。",
                    improvement_hint="ユーザーが求める結論、原因候補、次アクションを回答本文と shared summary に明示してください。",
                )
            )
        elif "shared memory" in normalized and "反映" in normalized:
            criteria.append(
                InstructionCriterion(
                    key="shared_memory",
                    title="shared memory への情報反映",
                    viewpoint="次工程に必要な情報が shared memory に反映され、後続処理が参照できる状態かを確認する。",
                    improvement_hint="次工程に必要な判断材料を shared memory の context / progress / summary に明示的に残してください。",
                )
            )
        elif "working memory" in normalized and "伝達漏れ" in normalized:
            criteria.append(
                InstructionCriterion(
                    key="working_memory_handoff",
                    title="working memory 起因の伝達漏れ",
                    viewpoint="各エージェントの working memory にしかない重要情報が shared memory に伝播されているかを確認する。",
                    improvement_hint="working memory にしかない重要情報は shared memory に要約転記し、引き継ぎ漏れを防いでください。",
                )
            )
        elif "SuperVisorAgent" in normalized and "最終状態" in normalized:
            criteria.append(
                InstructionCriterion(
                    key="supervisor_judgement",
                    title="SuperVisorAgent 判断の妥当性",
                    viewpoint="SuperVisorAgent の判断が最終状態と整合し、判断根拠や記録不足がないかを確認する。",
                    improvement_hint="SuperVisorAgent の判断根拠と最終状態との対応を shared summary に短く残してください。",
                )
            )
        elif "Summary" in normalized and "Adopted sources" in normalized:
            criteria.append(
                InstructionCriterion(
                    key="structured_fields",
                    title="構造化項目の記録充足",
                    viewpoint="Summary、Adopted sources、Intake category、Intake urgency などの構造化項目が欠けずに記録されているかを確認する。",
                    improvement_hint="Summary、Adopted sources、Intake category、Intake urgency などの構造化項目を欠落なく shared memory に残してください。",
                )
            )
    if checklist:
        criteria.append(
            InstructionCriterion(
                key="user_checklist",
                title="ユーザー指定観点の充足",
                viewpoint="ユーザーが明示した観点が評価対象に含まれ、結果と改善提案に反映されているかを確認する。",
                improvement_hint="ユーザーが明示した観点ごとに、根拠・評価結果・改善案を対応付けて記録してください。",
            )
        )
    return _dedupe_instruction_criteria(criteria)


def _extract_markdown_bullets(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    in_section = False
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return bullets


def _dedupe_instruction_criteria(criteria: list[InstructionCriterion]) -> list[InstructionCriterion]:
    deduped: list[InstructionCriterion] = []
    seen: set[str] = set()
    for item in criteria:
        if item.key in seen:
            continue
        seen.add(item.key)
        deduped.append(item)
    return deduped


def _assess_checklist_items(
    checklist: list[str],
    state: CaseState,
    context_text: str,
    progress_text: str,
    summary_text: str,
) -> list[tuple[str, str]]:
    if not checklist:
        return []
    corpus = "\n".join([
        str(state.get("raw_issue") or ""),
        str(state.get("investigation_summary") or ""),
        str(state.get("draft_response") or state.get("escalation_draft") or ""),
        context_text,
        progress_text,
        summary_text,
    ])
    assessments: list[tuple[str, str]] = []
    for item in checklist:
        status = "manual review required"
        if item in corpus:
            status = "matched"
        assessments.append((item, status))
    return assessments


def _render_checklist(criteria: list[CriterionEvaluation], checklist: list[str]) -> list[str]:
    if not checklist:
        return ["- なし"]
    checklist_map = _index_checklist_criteria(criteria)
    lines: list[str] = []
    for item in checklist:
        criterion = checklist_map.get(item.casefold())
        if criterion is None:
            lines.append(f"- [missing in evaluation] {item}")
            continue
        lines.append(f"- [{_checklist_badge(criterion.score)}] {item}: {criterion.result}")
    return lines or ["- なし"]


def _index_checklist_criteria(criteria: list[CriterionEvaluation]) -> dict[str, CriterionEvaluation]:
    index: dict[str, CriterionEvaluation] = {}
    for criterion in criteria:
        for item in criterion.related_checklist_items:
            key = item.strip().casefold()
            if key and key not in index:
                index[key] = criterion
    return index


def _checklist_badge(score: int) -> str:
    if score >= 80:
        return "good"
    if score >= 50:
        return "needs attention"
    return "needs improvement"


def _merge_missing_checklist_criteria(
    criteria: list[CriterionEvaluation],
    checklist_assessments: list[tuple[str, str]],
) -> list[CriterionEvaluation]:
    if not checklist_assessments:
        return criteria
    present = {
        item.casefold()
        for criterion in criteria
        for item in criterion.related_checklist_items
        if item.strip()
    }
    merged = list(criteria)
    for checklist_item, status in checklist_assessments:
        key = checklist_item.casefold()
        if key in present:
            continue
        score = 100 if status == "matched" else 40
        merged.append(
            CriterionEvaluation(
                criterion_key="user_checklist",
                name=f"ユーザー指定観点: {checklist_item}",
                viewpoint=f"インタラクションで指定された評価項目「{checklist_item}」が、回答本文・調査要約・共有メモリに反映されているかを確認する。",
                result=(
                    "関連記述を成果物と共有メモリから直接確認できました。"
                    if status == "matched"
                    else "関連記述を成果物または共有メモリから十分に確認できず、追加の明示が必要です。"
                ),
                score=score,
                related_checklist_items=[checklist_item],
            )
        )
    return merged


def _merge_missing_instruction_criteria(
    criteria: list[CriterionEvaluation],
    instruction_criteria: list[InstructionCriterion],
) -> list[CriterionEvaluation]:
    if not instruction_criteria:
        return criteria
    merged = list(criteria)
    for instruction_criterion in instruction_criteria:
        if _find_matching_criterion(merged, instruction_criterion) is not None:
            continue
        merged.append(
            CriterionEvaluation(
                criterion_key=instruction_criterion.key,
                name=instruction_criterion.title,
                viewpoint=instruction_criterion.viewpoint,
                result="Evaluator 出力にこの instruction 由来の評価観点が含まれておらず、観点に対する判定結果を確認できませんでした。",
                score=0,
            )
        )
    return merged


def _find_matching_criterion(
    criteria: list[CriterionEvaluation],
    instruction_criterion: InstructionCriterion,
) -> CriterionEvaluation | None:
    for criterion in criteria:
        if criterion.criterion_key == instruction_criterion.key:
            return criterion
        normalized_name = _normalize_text(criterion.name)
        normalized_viewpoint = _normalize_text(criterion.viewpoint)
        if _normalize_text(instruction_criterion.title) in normalized_name:
            return criterion
        if _normalize_text(instruction_criterion.viewpoint)[:20] and _normalize_text(instruction_criterion.viewpoint)[:20] in normalized_viewpoint:
            return criterion
    return None


def _merge_checklist_improvement_points(
    improvement_points: list[str],
    checklist_assessments: list[tuple[str, str]],
) -> list[str]:
    merged = list(improvement_points)
    existing_text = "\n".join(improvement_points).casefold()
    for checklist_item, status in checklist_assessments:
        if status == "matched":
            continue
        candidate = (
            f"ユーザー指定観点「{checklist_item}」を満たしたことが分かる根拠を、回答本文または shared memory に明示的に残してください。"
        )
        if candidate.casefold() in existing_text:
            continue
        merged.append(candidate)
    return merged


def _merge_instruction_improvement_points(
    improvement_points: list[str],
    criteria: list[CriterionEvaluation],
    instruction_criteria: list[InstructionCriterion],
) -> list[str]:
    merged = list(improvement_points)
    existing_points = [_normalize_improvement_point(item) for item in improvement_points if item.strip()]
    for instruction_criterion in instruction_criteria:
        criterion = _find_matching_criterion(criteria, instruction_criterion)
        if criterion is None:
            continue
        if criterion.score >= 70:
            continue
        normalized_hint = _normalize_improvement_point(instruction_criterion.improvement_hint)
        if any(_is_similar_improvement_point(normalized_hint, existing) for existing in existing_points):
            continue
        merged.append(instruction_criterion.improvement_hint)
        existing_points.append(normalized_hint)
    return merged


def _postprocess_criterion_evaluations(
    criteria: list[CriterionEvaluation],
    *,
    state: CaseState,
    shared_memory: dict[str, str],
    memory_findings: list[MemoryConsistencyFinding],
) -> list[CriterionEvaluation]:
    workflow_kind = _effective_workflow_kind(state)
    policy_gap_recorded = _policy_gap_is_recorded(shared_memory)
    has_unshared_memory_warning = _has_unshared_memory_warning(memory_findings)
    intake_working_gap = _has_intake_working_memory_gap(memory_findings)

    normalized: list[CriterionEvaluation] = []
    for criterion in criteria:
        updated = CriterionEvaluation(
            name=criterion.name,
            viewpoint=criterion.viewpoint,
            result=criterion.result,
            score=criterion.score,
            criterion_key=criterion.criterion_key,
            related_checklist_items=list(criterion.related_checklist_items),
        )
        if updated.criterion_key == "question_intent" and workflow_kind == "specification_inquiry":
            updated.viewpoint = updated.viewpoint.replace("結論・原因・次アクション", "結論・確認できた仕様や使い方・次アクション")
        if updated.criterion_key == "shared_memory" and policy_gap_recorded and _mentions_missing_explicit_record(updated.result):
            updated.result = "shared memory に基本情報は反映されており、ポリシー根拠の取得が未完了である点も context / progress に記録されています。"
            updated.score = max(updated.score, 80)
        if updated.criterion_key == "supervisor_judgement" and policy_gap_recorded and _mentions_missing_explicit_record(updated.result):
            updated.result = "SuperVisorAgent の判断は最終状態と整合しており、ポリシー根拠の取得未完了も shared memory に記録されています。"
            updated.score = max(updated.score, 80)
        if updated.criterion_key == "working_memory_handoff" and not has_unshared_memory_warning:
            if intake_working_gap:
                updated.result = "shared memory への重要情報の伝播漏れは確認できませんでした。一方で IntakeAgent の working memory 記録が薄く、処理経緯の追跡性には改善余地があります。"
                updated.score = max(updated.score, 78)
            else:
                updated.result = "working memory から shared memory への重要情報の伝播漏れは確認できませんでした。"
                updated.score = max(updated.score, 85)
        normalized.append(updated)
    return normalized


def _sanitize_improvement_points(
    improvement_points: list[str],
    *,
    state: CaseState,
    shared_memory: dict[str, str],
    memory_findings: list[MemoryConsistencyFinding],
) -> list[str]:
    workflow_kind = _effective_workflow_kind(state)
    policy_gap_recorded = _policy_gap_is_recorded(shared_memory)
    has_unshared_memory_warning = _has_unshared_memory_warning(memory_findings)

    sanitized: list[str] = []
    for point in improvement_points:
        normalized = _normalize_improvement_point(point)
        if policy_gap_recorded and "ポリシー根拠の取得が未完了であることを shared memory に明示" in point:
            continue
        if not has_unshared_memory_warning and "working memory にしかない重要情報" in point:
            continue
        if workflow_kind == "specification_inquiry" and "原因候補" in normalized:
            continue
        if point not in sanitized:
            sanitized.append(point)
    return sanitized


def _sanitize_overall_summary(
    overall_summary: str,
    *,
    shared_memory: dict[str, str],
) -> str:
    if _policy_gap_is_recorded(shared_memory):
        overall_summary = overall_summary.replace(
            "ポリシー根拠の取得が未完了であることが明示されておらず、次工程での参照に不安が残る。",
            "ポリシー根拠の取得は未完了ですが、その旨は shared memory に記録されています。",
        )
    return overall_summary


def _policy_gap_is_recorded(shared_memory: dict[str, str]) -> bool:
    corpus = _normalize_text("\n".join(shared_memory.values()))
    markers = (
        _normalize_text("ポリシー根拠の取得は未完了"),
        _normalize_text("確認根拠となるポリシー文書を取得できませんでした"),
    )
    return any(marker and marker in corpus for marker in markers)


def _has_unshared_memory_warning(memory_findings: list[MemoryConsistencyFinding]) -> bool:
    return any("shared memory に反映されていません" in item.detail for item in memory_findings)


def _has_intake_working_memory_gap(memory_findings: list[MemoryConsistencyFinding]) -> bool:
    return any(
        item.agent_name == "IntakeAgent" and "working memory に見当たらず" in item.detail
        for item in memory_findings
    )


def _mentions_missing_explicit_record(text: str) -> bool:
    return any(marker in text for marker in ("明示されていない", "明示されておらず"))


def _normalize_improvement_point(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    normalized = normalized.removesuffix("してください。")
    normalized = normalized.removesuffix("してください")
    normalized = normalized.removesuffix("する。")
    normalized = normalized.removesuffix("する")
    normalized = normalized.removesuffix("残してください。")
    normalized = normalized.removesuffix("残してください")
    normalized = normalized.removesuffix("残す。")
    normalized = normalized.removesuffix("残す")
    normalized = normalized.removesuffix("防いでください。")
    normalized = normalized.removesuffix("防いでください")
    normalized = normalized.removesuffix("防ぐ。")
    normalized = normalized.removesuffix("防ぐ")
    return normalized.strip()


def _is_similar_improvement_point(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    common_prefix = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        common_prefix += 1
    return common_prefix >= 24


def _render_compliance_review_history(history: list[dict[str, object]]) -> list[str]:
    normalized = [item for item in history if isinstance(item, dict)]
    if not normalized:
        return ["- なし"]

    lines: list[str] = []
    for entry in normalized:
        iteration = str(entry.get("iteration") or "?")
        passed = bool(entry.get("passed"))
        raw_issues = entry.get("compliance_review_issues")
        issues_source = raw_issues if isinstance(raw_issues, list) else []
        issues = [str(item).strip() for item in issues_source if str(item).strip()]
        addressed_revision_request = str(entry.get("addressed_revision_request") or "").strip()
        revision_request = str(entry.get("compliance_revision_request") or "").strip()
        review_focus = str(entry.get("review_focus") or "").strip()
        draft_excerpt = str(entry.get("draft_excerpt") or "").strip()
        review_summary = str(entry.get("compliance_review_summary") or "").strip()
        raw_adopted_sources = entry.get("adopted_sources")
        adopted_source_values = raw_adopted_sources if isinstance(raw_adopted_sources, list) else []
        adopted_sources = [str(item).strip() for item in adopted_source_values if str(item).strip()]
        response_summary = _summarize_compliance_response(
            addressed_revision_request=addressed_revision_request,
            draft_excerpt=draft_excerpt,
            passed=passed,
            review_summary=review_summary,
        )
        lines.extend(
            [
                f"### Review Iteration {iteration}",
                f"- 判定: {'passed' if passed else 'revision required'}",
                f"- Review focus: {review_focus or 'n/a'}",
                f"- 対応対象の指摘: {addressed_revision_request or '初回ドラフトのレビュー'}",
                f"- 指摘内容: {' | '.join(issues) if issues else 'なし'}",
                f"- 修正依頼: {revision_request or 'なし'}",
                f"- 対応内容: {response_summary}",
                f"- レビュー要約: {review_summary or 'なし'}",
                f"- 採用した根拠ソース: {', '.join(adopted_sources) if adopted_sources else 'なし'}",
                "",
            ]
        )
    if lines and not lines[-1].strip():
        lines.pop()
    return lines


def _summarize_compliance_response(
    *,
    addressed_revision_request: str,
    draft_excerpt: str,
    passed: bool,
    review_summary: str,
) -> str:
    normalized_request = re.sub(r"\s+", " ", addressed_revision_request.strip())
    normalized_draft = re.sub(r"\s+", " ", draft_excerpt.strip())
    normalized_review_summary = re.sub(r"\s+", " ", review_summary.strip())

    if not normalized_request and "継続可能と判断" in normalized_review_summary:
        audience = "サポート担当者向け回答"
        if "顧客向けの直接回答" in normalized_review_summary:
            audience = "顧客向けの直接回答"
        result = f"具体的な文面修正は行わず、レビュー結果を踏まえて{audience}として継続可能と判断しました。"
        if normalized_draft:
            result += f" 対象ドラフト: 「{normalized_draft}」"
        return result

    if normalized_request and normalized_draft:
        result = f"前回の修正依頼「{normalized_request}」に対応し、ドラフトを「{normalized_draft}」へ更新しました。"
    elif normalized_request:
        result = f"前回の修正依頼「{normalized_request}」に対応して再レビューしました。"
    elif normalized_draft:
        result = f"初回ドラフトとして「{normalized_draft}」を作成しました。"
    else:
        result = "対応内容の記録はありません。"

    if passed and normalized_review_summary:
        result += f" 最終的に {normalized_review_summary}"
    return result


def _format_agent_evaluation(evaluation: AgentEvaluation) -> str:
    evidence_suffix = f" | 根拠: {' / '.join(evaluation.evidence[:2])}" if evaluation.evidence else ""
    return (
        f"{evaluation.agent_name}: {evaluation.score} / 100 - "
        f"{'good' if evaluation.is_good else 'needs improvement'} - {evaluation.detail}{evidence_suffix}"
    )


def _format_memory_finding(finding: MemoryConsistencyFinding) -> str:
    return f"[{finding.severity}] {finding.agent_name}: {finding.detail}"


def _render_criterion_evaluations(criteria: list[CriterionEvaluation]) -> list[str]:
    if not criteria:
        return ["- なし"]
    lines: list[str] = []
    for item in criteria:
        checklist_line = ""
        if item.related_checklist_items:
            checklist_line = f"- 対応するユーザー指定観点: {', '.join(item.related_checklist_items)}"
        lines.extend([
            f"### {item.name}",
            f"- 評価観点: {item.viewpoint}",
            f"- 評価結果: {item.result}",
            f"- 点数: {item.score} / 100",
            *( [checklist_line] if checklist_line else [] ),
            "",
        ])
    if lines and not lines[-1].strip():
        lines.pop()
    return lines


def _render_subgraph_sequence_section(diagrams: list[SubgraphSequenceDiagram]) -> list[str]:
    if not diagrams:
        return ["- なし"]
    lines: list[str] = []
    for item in diagrams:
        lines.extend([
            f"### {item.title}",
            "```mermaid",
            item.diagram,
            "```",
            "",
        ])
    if lines and not lines[-1].strip():
        lines.pop()
    return lines


def _load_agent_memories(case_paths: Any, memory_store: CaseMemoryStore) -> dict[str, str]:
    memories: dict[str, str] = {}
    if not case_paths.agents_dir.exists():
        return memories
    for working_file in sorted(case_paths.agents_dir.glob("*/working.md")):
        memories[working_file.parent.name] = memory_store.read_text(working_file)
    return memories


def _audit_memory_consistency(
    state: CaseState,
    shared_memory: dict[str, str],
    agent_memories: dict[str, str],
) -> list[MemoryConsistencyFinding]:
    findings: list[MemoryConsistencyFinding] = []
    shared_corpus = _normalize_text("\n".join(shared_memory.values()))
    raw_agent_memories = {name: text for name, text in agent_memories.items()}
    normalized_agent_memories = {name: _normalize_memory_text(text) for name, text in raw_agent_memories.items()}
    for agent_name, label, value, shared_markers, agent_markers in _build_memory_expectations(state):
        normalized_value = _normalize_text(value)
        if not normalized_value:
            continue
        if shared_markers and not _memory_field_covered(shared_corpus, normalized_value, shared_markers):
            findings.append(MemoryConsistencyFinding(
                agent_name=agent_name,
                severity="warning",
                detail=f"{label} が shared memory に見当たらず、次工程へ十分に伝播していない可能性があります。",
            ))
        if agent_markers and not _memory_field_covered(normalized_agent_memories.get(agent_name, ""), normalized_value, agent_markers):
            findings.append(MemoryConsistencyFinding(
                agent_name=agent_name,
                severity="warning",
                detail=f"{label} が {agent_name} の working memory に見当たらず、処理経緯の追跡性が弱くなっています。",
            ))

    expectation_map = _build_expectation_lookup(_build_memory_expectations(state))
    for agent_name, memory_text in raw_agent_memories.items():
        private_lines = _unshared_memory_lines(memory_text, shared_corpus, expectation_map.get(agent_name, ()))
        if private_lines:
            findings.append(MemoryConsistencyFinding(
                agent_name=agent_name,
                severity="warning",
                detail=f"working memory の記述 {', '.join(private_lines[:2])} が shared memory に反映されていません。",
            ))
    return findings


def _build_memory_expectations(state: CaseState) -> list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]]:
    expectations: list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = [
        ("IntakeAgent", "問い合わせ分類", str(state.get("intake_category") or ""), ("intake category",), ("category:", "intake category:")),
        ("IntakeAgent", "緊急度", str(state.get("intake_urgency") or ""), ("intake urgency",), ("urgency:", "intake urgency:")),
        ("KnowledgeRetrieverAgent", "採用ナレッジ", ", ".join(list(state.get("knowledge_retrieval_adopted_sources") or [])), ("採用した根拠ソース",), ("adopted sources:",)),
    ]
    workflow_kind = _effective_workflow_kind(state)
    if workflow_kind in {"incident_investigation", "ambiguous_case"}:
        expectations.append(("LogAnalyzerAgent", "ログ解析要約", str(state.get("log_analysis_summary") or ""), ("ログ解析結果",), ("summary:", "file:")))
    if bool(state.get("escalation_required")):
        expectations.append(("BackSupportEscalationAgent", "エスカレーション要約", str(state.get("escalation_summary") or ""), ("エスカレーション理由", "調査要約"), tuple()))
        expectations.append(("BackSupportInquiryWriterAgent", "バックサポート向け問い合わせ文案", str(state.get("escalation_draft") or ""), tuple(), tuple()))
    else:
        expectations.append(("ComplianceReviewerAgent", "コンプライアンス要約", str(state.get("compliance_review_summary") or ""), ("コンプライアンス",), tuple()))
        expectations.append(("DraftWriterAgent", "回答ドラフト", str(state.get("draft_response") or ""), tuple(), tuple()))
    return expectations


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _build_expectation_lookup(
    expectations: list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]],
) -> dict[str, tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...]]:
    grouped: dict[str, list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]] = {}
    for agent_name, _label, value, shared_markers, agent_markers in expectations:
        normalized_value = _normalize_text(value)
        if not normalized_value:
            continue
        grouped.setdefault(agent_name, []).append((normalized_value, value, shared_markers, agent_markers))
    return {agent_name: tuple(items) for agent_name, items in grouped.items()}


def _normalize_memory_text(value: str) -> str:
    lines: list[str] = []
    for raw_line in value.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("# Working Memory:"):
            continue
        if stripped in {"# Shared Context", "# Shared Progress", "# Shared Summary"}:
            continue
        lines.append(stripped)
    return _normalize_text("\n".join(lines))


def _text_covered(corpus: str, value: str) -> bool:
    if not corpus or not value:
        return False
    if value in corpus:
        return True
    fragments = [fragment.strip() for fragment in value.split("。") if len(fragment.strip()) >= 12]
    if fragments:
        return any(fragment in corpus for fragment in fragments)
    shortened = value[:80].strip()
    return bool(shortened) and shortened in corpus


def _instruction_excerpt(value: str) -> str:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:120]
    return ""


def _unshared_memory_lines(
    memory_text: str,
    shared_corpus: str,
    expectations: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...],
) -> list[str]:
    if not memory_text:
        return []
    candidates: list[str] = []
    for line in memory_text.splitlines():
        stripped = line.strip().lstrip("- ")
        normalized = _normalize_text(stripped)
        if len(normalized) < 16:
            continue
        if stripped.startswith("#"):
            continue
        if _should_ignore_private_memory_line(normalized):
            continue
        if _line_is_semantically_shared(stripped, normalized, shared_corpus, expectations):
            continue
        if normalized not in shared_corpus and stripped[:40] not in candidates:
            candidates.append(stripped[:40])
    return candidates[:2]


def _should_ignore_private_memory_line(normalized_line: str) -> bool:
    ignored_prefixes = (
        "external ticket id: ext-trace-",
        "internal ticket id: int-trace-",
        "raw result: {",
    )
    ignored_exact = {
        "review focus: n/a",
        "adopted sources: none",
        "issues: none",
    }
    return normalized_line in ignored_exact or any(normalized_line.startswith(prefix) for prefix in ignored_prefixes)


def _line_is_semantically_shared(
    line: str,
    normalized_line: str,
    shared_corpus: str,
    expectations: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...],
) -> bool:
    if normalized_line in shared_corpus:
        return True
    value_part = normalized_line.split(":", 1)[1].strip() if ":" in normalized_line else ""
    if value_part and value_part in shared_corpus:
        return True
    for normalized_value, raw_value, shared_markers, agent_markers in expectations:
        if normalized_value and normalized_value in normalized_line:
            if _memory_field_covered(shared_corpus, normalized_value, shared_markers):
                return True
            if value_part and _text_covered(shared_corpus, value_part):
                return True
        if agent_markers and any(_normalize_text(marker) in normalized_line for marker in agent_markers):
            if value_part and _memory_field_covered(shared_corpus, value_part, shared_markers):
                return True
            if raw_value and _memory_field_covered(shared_corpus, _normalize_text(raw_value), shared_markers):
                return True
    return False


def _memory_field_covered(corpus: str, value: str, markers: tuple[str, ...]) -> bool:
    if not corpus:
        return False
    if value and _text_covered(corpus, value):
        return True
    return any(_normalize_text(marker) in corpus for marker in markers)


def _report_item(label: str, value: Any, description: str) -> list[str]:
    return [
        f"- {label}: {value}",
        f"  説明: {description}",
    ]