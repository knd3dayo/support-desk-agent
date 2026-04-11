from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from support_ope_agents.agents.roles import OBJECTIVE_EVALUATION_AGENT
from support_ope_agents.config.models import AppConfig, ObjectiveEvaluationAgentSettings
from support_ope_agents.instructions.loader import InstructionLoader
from support_ope_agents.memory.file_store import CaseMemoryStore
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
class ObjectiveEvaluation:
    evaluator_name: str
    instruction_excerpt: str
    sequence_diagram: str
    subgraph_sequence_diagrams: list[SubgraphSequenceDiagram]
    agent_evaluations: list[AgentEvaluation]
    memory_findings: list[MemoryConsistencyFinding]
    overall_summary: str
    improvement_points: list[str]
    score: int


class ObjectiveEvaluationAgent:
    name = OBJECTIVE_EVALUATION_AGENT

    def __init__(self, settings: ObjectiveEvaluationAgentSettings, instruction_text: str):
        self._settings = settings
        self._instruction_text = instruction_text.strip()

    def evaluate(
        self,
        *,
        state: CaseState,
        case_paths: Any,
        memory_store: CaseMemoryStore,
        context_text: str,
        progress_text: str,
        summary_text: str,
    ) -> ObjectiveEvaluation:
        shared_memory = {
            "context": context_text,
            "progress": progress_text,
            "summary": summary_text,
        }
        agent_memories = _load_agent_memories(case_paths, memory_store)
        memory_findings = _audit_memory_consistency(state, shared_memory, agent_memories)
        agent_evaluations = _evaluate_agents(state, memory_findings, self._settings)
        overall_summary = _build_overall_summary(state, agent_evaluations, memory_findings)
        improvement_points = _build_improvement_points(agent_evaluations, memory_findings)
        score = _calculate_overall_score(agent_evaluations)
        return ObjectiveEvaluation(
            evaluator_name=self.name,
            instruction_excerpt=_instruction_excerpt(self._instruction_text),
            sequence_diagram=_build_sequence_diagram(state),
            subgraph_sequence_diagrams=_build_subgraph_sequence_diagrams(state),
            agent_evaluations=agent_evaluations,
            memory_findings=memory_findings,
            overall_summary=overall_summary,
            improvement_points=improvement_points,
            score=score,
        )


def build_support_improvement_report(
    *,
    case_id: str,
    trace_id: str,
    workspace_path: str,
    state: CaseState,
    memory_store: CaseMemoryStore,
    instruction_loader: InstructionLoader,
    config: AppConfig,
    checklist: list[str] | None = None,
) -> EvaluationReportResult:
    case_paths = memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
    context_text = memory_store.read_text(case_paths.shared_context)
    progress_text = memory_store.read_text(case_paths.shared_progress)
    summary_text = memory_store.read_text(case_paths.shared_summary)
    artifact_paths = [path.relative_to(case_paths.root).as_posix() for path in memory_store.list_artifacts(case_id, workspace_path)]

    evaluator_settings = config.agents.ObjectiveEvaluationAgent
    evaluator_instruction = instruction_loader.load(case_id, OBJECTIVE_EVALUATION_AGENT)
    evaluation = ObjectiveEvaluationAgent(evaluator_settings, evaluator_instruction).evaluate(
        state=state,
        case_paths=case_paths,
        memory_store=memory_store,
        context_text=context_text,
        progress_text=progress_text,
        summary_text=summary_text,
    )
    checklist_section = _render_checklist(checklist or [], state, context_text, progress_text, summary_text)

    report_lines = [
        f"# Support Improvement Report: {case_id}",
        "",
        "## Meta",
        *_report_item("Case ID", case_id, "レポート対象のケースを一意に識別するIDです。"),
        *_report_item("Trace ID", trace_id, "今回の実行トレースを追跡するための識別子です。"),
        *_report_item("Workspace", case_paths.root, "ケース関連ファイルと成果物を保存した作業ディレクトリです。"),
        *_report_item("Final status", str(state.get("status") or "unknown"), "ワークフロー完了時点の最終ステータスです。"),
        *_report_item("Evaluator", evaluation.evaluator_name, "SuperVisor ではなく、決め打ちルールで評価する客観評価エージェントです。"),
        *_report_item("Evaluation rubric", evaluation.instruction_excerpt or "n/a", "Evaluator instruction の冒頭要約です。"),
        "",
        "## 問い合わせ内容",
        "問い合わせ原文または整形後の主訴です。調査対象の起点として参照します。",
        str(state.get("raw_issue") or "n/a"),
        "",
        "## 回答内容",
        "顧客向けに返却した、または返却予定の回答本文です。",
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
        "## 総合評価",
        "### 総評",
        "ケース全体を通した自動対応品質の総括です。ObjectiveEvaluationAgent が固定基準で判定しています。",
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


def _build_sequence_diagram(state: CaseState) -> str:
    lines = [
        "sequenceDiagram",
        "    participant User as User",
        "    participant Intake as IntakeAgent",
        "    participant Supervisor as SuperVisorAgent",
        "    participant LogAnalyzer as LogAnalyzerAgent",
        "    participant Knowledge as KnowledgeRetrieverAgent",
        "    participant DraftWriter as DraftWriterAgent",
        "    participant Compliance as ComplianceReviewerAgent",
        "    participant Approval as ApprovalAgent",
        "    participant TicketUpdate as TicketUpdateAgent",
        "    participant Escalation as BackSupportEscalationAgent",
        "    participant Inquiry as BackSupportInquiryWriterAgent",
        "    User->>Intake: 問い合わせ入力",
        "    Intake->>Supervisor: Intake 結果を引き渡し",
    ]
    workflow_kind = _effective_workflow_kind(state)
    if workflow_kind in {"incident_investigation", "ambiguous_case"}:
        lines.append("    Supervisor->>LogAnalyzer: ログ解析を依頼")
        lines.append("    LogAnalyzer-->>Supervisor: ログ解析結果を返却")
    lines.append("    Supervisor->>Knowledge: ナレッジ検索を依頼")
    lines.append("    Knowledge-->>Supervisor: 検索結果を返却")
    if bool(state.get("escalation_required")):
        lines.append("    Supervisor->>Escalation: エスカレーション判断と要約を依頼")
        lines.append("    Escalation->>Inquiry: 問い合わせ文案作成を依頼")
        lines.append("    Inquiry-->>Supervisor: エスカレーション文案を返却")
    else:
        lines.append("    Supervisor->>DraftWriter: 回答ドラフト作成を依頼")
        review_iterations = int(state.get("draft_review_iterations") or 1)
        for _ in range(max(1, review_iterations)):
            lines.append("    DraftWriter-->>Supervisor: ドラフトを返却")
            lines.append("    Supervisor->>Compliance: コンプライアンス確認を依頼")
            lines.append("    Compliance-->>Supervisor: レビュー結果を返却")
        lines.append("    Supervisor->>Approval: 承認依頼を送信")
        if str(state.get("status") or "") == "CLOSED" or str(state.get("ticket_update_result") or ""):
            lines.append("    Approval->>TicketUpdate: 承認済み更新を依頼")
            lines.append("    TicketUpdate-->>User: 更新完了")
    return "\n".join(lines)


def _build_subgraph_sequence_diagrams(state: CaseState) -> list[SubgraphSequenceDiagram]:
    diagrams = [
        SubgraphSequenceDiagram(
            title="IntakeAgent サブグラフ",
            diagram="\n".join([
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
            ]),
        )
    ]
    if not bool(state.get("escalation_required")):
        review_iterations = int(state.get("draft_review_iterations") or 1)
        review_lines = [
            "sequenceDiagram",
            "    participant Supervisor as SuperVisorAgent",
            "    participant DraftWriter as DraftWriterAgent",
            "    participant Compliance as ComplianceReviewerAgent",
            "    Supervisor->>DraftWriter: 回答ドラフト作成を依頼",
        ]
        for index in range(max(1, review_iterations)):
            review_lines.append(f"    DraftWriter-->>Supervisor: ドラフトを返却 ({index + 1})")
            review_lines.append(f"    Supervisor->>Compliance: レビュー依頼 ({index + 1})")
            review_lines.append(f"    Compliance-->>Supervisor: レビュー結果を返却 ({index + 1})")
        diagrams.append(
            SubgraphSequenceDiagram(
                title="Draft Review ループ",
                diagram="\n".join(review_lines),
            )
        )
    if bool(state.get("escalation_required")):
        diagrams.append(
            SubgraphSequenceDiagram(
                title="Escalation 準備フロー",
                diagram="\n".join([
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
                ]),
            )
        )
    if str(state.get("status") or "") == "CLOSED" or str(state.get("ticket_update_result") or "").strip():
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


def _evaluate_agents(
    state: CaseState,
    memory_findings: list[MemoryConsistencyFinding],
    settings: ObjectiveEvaluationAgentSettings,
) -> list[AgentEvaluation]:
    evaluations: list[AgentEvaluation] = []
    finding_map = _group_findings_by_agent(memory_findings)
    intake_ok = bool(state.get("intake_category")) and not bool(state.get("intake_rework_required"))
    evaluations.append(_build_agent_evaluation(
        state,
        agent_name="IntakeAgent",
        primary_ok=intake_ok,
        detail=f"分類と前処理 {'完了' if intake_ok else '要再確認'}",
        improvement_point=None if intake_ok else "問い合わせ分類または前処理結果を見直し、再実行条件を明確化してください。",
        finding_map=finding_map,
        settings=settings,
    ))
    workflow_kind = _effective_workflow_kind(state)
    if workflow_kind in {"incident_investigation", "ambiguous_case"}:
        log_ok = bool(str(state.get("log_analysis_summary") or "").strip())
        evaluations.append(_build_agent_evaluation(
            state,
            agent_name="LogAnalyzerAgent",
            primary_ok=log_ok,
            detail=f"ログ解析結果 {'あり' if log_ok else 'なし'}",
            improvement_point=None if log_ok else "調査対象ログの特定と解析結果の要約を補強してください。",
            finding_map=finding_map,
            settings=settings,
        ))
    knowledge_ok = bool(list(state.get("knowledge_retrieval_adopted_sources") or []))
    evaluations.append(_build_agent_evaluation(
        state,
        agent_name="KnowledgeRetrieverAgent",
        primary_ok=knowledge_ok,
        detail=f"採用ナレッジソース {', '.join(list(state.get('knowledge_retrieval_adopted_sources') or [])) or 'なし'}",
        improvement_point=None if knowledge_ok else "採用根拠となるナレッジソースを追加し、参照結果を明示してください。",
        finding_map=finding_map,
        settings=settings,
    ))
    if bool(state.get("escalation_required")):
        escalation_ok = bool(str(state.get("escalation_summary") or "").strip()) and bool(str(state.get("escalation_draft") or "").strip())
        evaluations.append(_build_agent_evaluation(
            state,
            agent_name="BackSupportEscalationAgent",
            primary_ok=escalation_ok,
            detail=f"エスカレーション要約 {'あり' if escalation_ok else 'なし'}",
            improvement_point=None if escalation_ok else "エスカレーション判断の根拠と要約内容を具体化してください。",
            finding_map=finding_map,
            settings=settings,
        ))
        evaluations.append(_build_agent_evaluation(
            state,
            agent_name="BackSupportInquiryWriterAgent",
            primary_ok=escalation_ok,
            detail=f"問い合わせ文案 {'あり' if escalation_ok else 'なし'}",
            improvement_point=None if escalation_ok else "バックサポート向け問い合わせ文案の必須情報を補完してください。",
            finding_map=finding_map,
            settings=settings,
        ))
    else:
        draft_ok = bool(str(state.get("draft_response") or "").strip())
        evaluations.append(_build_agent_evaluation(
            state,
            agent_name="DraftWriterAgent",
            primary_ok=draft_ok,
            detail=f"ドラフト {'あり' if draft_ok else 'なし'}",
            improvement_point=None if draft_ok else "顧客向け回答ドラフトの本文を補完し、結論と案内を明確にしてください。",
            finding_map=finding_map,
            settings=settings,
        ))
        compliance_ok = bool(state.get("compliance_review_passed"))
        evaluations.append(_build_agent_evaluation(
            state,
            agent_name="ComplianceReviewerAgent",
            primary_ok=compliance_ok,
            detail=f"レビュー {'通過' if compliance_ok else '未通過'}",
            improvement_point=None if compliance_ok else "レビュー差戻し論点を反映し、回答内容を再点検してください。",
            finding_map=finding_map,
            settings=settings,
        ))
    return evaluations


def _render_checklist(
    checklist: list[str],
    state: CaseState,
    context_text: str,
    progress_text: str,
    summary_text: str,
) -> list[str]:
    if not checklist:
        return ["- なし"]
    corpus = "\n".join([
        str(state.get("raw_issue") or ""),
        str(state.get("investigation_summary") or ""),
        str(state.get("draft_response") or ""),
        context_text,
        progress_text,
        summary_text,
    ])
    lines: list[str] = []
    for item in checklist:
        normalized = item.strip()
        if not normalized:
            continue
        status = "manual review required"
        if normalized in corpus:
            status = "matched"
        lines.append(f"- [{status}] {normalized}")
    return lines or ["- なし"]


def _build_overall_summary(
    state: CaseState,
    agent_scores: list[AgentEvaluation],
    memory_findings: list[MemoryConsistencyFinding],
) -> str:
    weak_count = sum(1 for item in agent_scores if not item.is_good)
    warning_count = sum(1 for item in memory_findings if item.severity == "warning")
    if bool(state.get("escalation_required")):
        return (
            "調査自体は成立していますが、確実な回答に必要な材料が不足しており、"
            f"客観評価ではエスカレーション判断を妥当とみなします。情報伝達上の注意点は {warning_count} 件です。"
        )
    if weak_count == 0 and warning_count == 0 and bool(state.get("compliance_review_passed")):
        return "主要エージェントの出力とメモリ連携は安定しており、顧客向け回答とレビューは客観基準でも良好です。"
    return (
        f"自動実行は完了しましたが、{weak_count} 件の品質課題と {warning_count} 件の情報伝達リスクがあります。"
        "差戻し論点と memory 監査結果を確認してください。"
    )


def _build_improvement_points(
    agent_scores: list[AgentEvaluation],
    memory_findings: list[MemoryConsistencyFinding],
) -> list[str]:
    items = [item.improvement_point for item in agent_scores if item.improvement_point]
    items.extend(item.detail for item in memory_findings if item.severity == "warning")
    deduplicated: list[str] = []
    for item in items:
        if item not in deduplicated:
            deduplicated.append(item)
    return deduplicated


def _calculate_overall_score(agent_scores: list[AgentEvaluation]) -> int:
    if not agent_scores:
        return 0
    return max(0, min(100, round(sum(item.score for item in agent_scores) / len(agent_scores))))


def _format_agent_evaluation(evaluation: AgentEvaluation) -> str:
    evidence_suffix = f" | 根拠: {' / '.join(evaluation.evidence[:2])}" if evaluation.evidence else ""
    return (
        f"{evaluation.agent_name}: {evaluation.score} / 100 - "
        f"{'good' if evaluation.is_good else 'needs improvement'} - {evaluation.detail}{evidence_suffix}"
    )


def _format_memory_finding(finding: MemoryConsistencyFinding) -> str:
    return f"[{finding.severity}] {finding.agent_name}: {finding.detail}"


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


def _build_agent_evaluation(
    state: CaseState,
    *,
    agent_name: str,
    primary_ok: bool,
    detail: str,
    improvement_point: str | None,
    finding_map: dict[str, list[MemoryConsistencyFinding]],
    settings: ObjectiveEvaluationAgentSettings,
) -> AgentEvaluation:
    warnings = finding_map.get(agent_name, [])
    agent_errors = list(state.get("agent_errors") or [])
    related_error_count = sum(
        1
        for item in agent_errors
        if agent_name.lower() in str(item.get("agent_name") or item.get("agent") or "").lower()
    )
    score = 100
    if not primary_ok:
        score -= settings.primary_failure_penalty
    score -= _warning_penalty(warnings, settings)
    score -= settings.agent_error_penalty * related_error_count
    score = max(0, min(100, score))
    evidence = [item.detail for item in warnings[:2]]
    if related_error_count:
        evidence.append(f"関連エラー {related_error_count} 件")
    detail_suffix = f" / memory warning {len(warnings)} 件" if warnings else ""
    effective_improvement = improvement_point
    if warnings:
        effective_improvement = improvement_point or warnings[0].detail
    return AgentEvaluation(
        agent_name=agent_name,
        score=score,
        is_good=primary_ok and score >= settings.pass_score,
        detail=f"{detail}{detail_suffix}",
        improvement_point=effective_improvement,
        evidence=evidence,
    )


def _group_findings_by_agent(findings: list[MemoryConsistencyFinding]) -> dict[str, list[MemoryConsistencyFinding]]:
    grouped: dict[str, list[MemoryConsistencyFinding]] = {}
    for item in findings:
        grouped.setdefault(item.agent_name, []).append(item)
    return grouped


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


def _warning_penalty(warnings: list[MemoryConsistencyFinding], settings: ObjectiveEvaluationAgentSettings) -> int:
    total = 0
    for item in warnings:
        if "shared memory" in item.detail:
            total += settings.missing_shared_memory_penalty
        elif "working memory" in item.detail:
            total += settings.missing_agent_memory_penalty
        else:
            total += settings.private_memory_penalty
    return total


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