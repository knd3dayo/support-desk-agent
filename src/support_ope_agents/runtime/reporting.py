from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    is_good: bool
    detail: str
    improvement_point: str | None = None


def build_support_improvement_report(
    *,
    case_id: str,
    trace_id: str,
    workspace_path: str,
    state: CaseState,
    memory_store: CaseMemoryStore,
    checklist: list[str] | None = None,
) -> EvaluationReportResult:
    case_paths = memory_store.resolve_case_paths(case_id, workspace_path=workspace_path)
    context_text = memory_store.read_text(case_paths.shared_context)
    progress_text = memory_store.read_text(case_paths.shared_progress)
    summary_text = memory_store.read_text(case_paths.shared_summary)
    artifact_paths = [path.relative_to(case_paths.root).as_posix() for path in memory_store.list_artifacts(case_id, workspace_path)]

    sequence_diagram = _build_sequence_diagram(state)
    agent_evaluations = _evaluate_agents(state)
    checklist_section = _render_checklist(checklist or [], state, context_text, progress_text, summary_text)
    overall_summary = _build_overall_summary(state, agent_evaluations)
    improvement_points = _build_improvement_points(state, agent_evaluations)
    score = _calculate_overall_score(state, agent_evaluations)

    report_lines = [
        f"# Support Improvement Report: {case_id}",
        "",
        "## Meta",
        *_report_item("Case ID", case_id, "レポート対象のケースを一意に識別するIDです。"),
        *_report_item("Trace ID", trace_id, "今回の実行トレースを追跡するための識別子です。"),
        *_report_item("Workspace", case_paths.root, "ケース関連ファイルと成果物を保存した作業ディレクトリです。"),
        *_report_item("Final status", str(state.get("status") or "unknown"), "ワークフロー完了時点の最終ステータスです。"),
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
        "ケース全体を通した自動対応品質の総括です。",
        overall_summary,
        "",
        "### 要改善点",
        "各エージェントや処理全体の課題、改善点を一覧化します。",
        *([f"- {item}" for item in improvement_points] or ["- なし"]),
        "",
        "### 点数",
        "0～100で評価します。",
        f"{score} / 100",
        "",
        "## エージェント呼び出しシーケンス",
        "問い合わせ受付から回答またはエスカレーションまでの呼び出し順を図示します。",
        "```mermaid",
        sequence_diagram,
        "```",
        "",
        "## エージェント別評価",
        "各エージェントの役割ごとに、出力の有無と品質を評価した一覧です。",
        *[f"- {_format_agent_evaluation(item)}" for item in agent_evaluations],
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
    return EvaluationReportResult(report_path=report_path, sequence_diagram=sequence_diagram, content=content)


def _result_label(state: CaseState) -> str:
    if bool(state.get("escalation_required")):
        return "エスカレーションが必要だった"
    if bool(state.get("compliance_review_passed")):
        return "確実な回答が得られた"
    return "回答ドラフトは作成されたが追加確認が必要"


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
    workflow_kind = str(state.get("workflow_kind") or "")
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


def _evaluate_agents(state: CaseState) -> list[AgentEvaluation]:
    evaluations: list[AgentEvaluation] = []
    intake_ok = bool(state.get("intake_category")) and not bool(state.get("intake_rework_required"))
    evaluations.append(AgentEvaluation(
        agent_name="IntakeAgent",
        is_good=intake_ok,
        detail=f"分類と前処理 {'完了' if intake_ok else '要再確認'}",
        improvement_point=None if intake_ok else "問い合わせ分類または前処理結果を見直し、再実行条件を明確化してください。",
    ))
    workflow_kind = str(state.get("workflow_kind") or "")
    if workflow_kind in {"incident_investigation", "ambiguous_case"}:
        log_ok = bool(str(state.get("log_analysis_summary") or "").strip())
        evaluations.append(AgentEvaluation(
            agent_name="LogAnalyzerAgent",
            is_good=log_ok,
            detail=f"ログ解析結果 {'あり' if log_ok else 'なし'}",
            improvement_point=None if log_ok else "調査対象ログの特定と解析結果の要約を補強してください。",
        ))
    knowledge_ok = bool(list(state.get("knowledge_retrieval_adopted_sources") or []))
    evaluations.append(AgentEvaluation(
        agent_name="KnowledgeRetrieverAgent",
        is_good=knowledge_ok,
        detail=f"採用ナレッジソース {', '.join(list(state.get('knowledge_retrieval_adopted_sources') or [])) or 'なし'}",
        improvement_point=None if knowledge_ok else "採用根拠となるナレッジソースを追加し、参照結果を明示してください。",
    ))
    if bool(state.get("escalation_required")):
        escalation_ok = bool(str(state.get("escalation_summary") or "").strip()) and bool(str(state.get("escalation_draft") or "").strip())
        evaluations.append(AgentEvaluation(
            agent_name="BackSupportEscalationAgent",
            is_good=escalation_ok,
            detail=f"エスカレーション要約 {'あり' if escalation_ok else 'なし'}",
            improvement_point=None if escalation_ok else "エスカレーション判断の根拠と要約内容を具体化してください。",
        ))
        evaluations.append(AgentEvaluation(
            agent_name="BackSupportInquiryWriterAgent",
            is_good=escalation_ok,
            detail=f"問い合わせ文案 {'あり' if escalation_ok else 'なし'}",
            improvement_point=None if escalation_ok else "バックサポート向け問い合わせ文案の必須情報を補完してください。",
        ))
    else:
        draft_ok = bool(str(state.get("draft_response") or "").strip())
        evaluations.append(AgentEvaluation(
            agent_name="DraftWriterAgent",
            is_good=draft_ok,
            detail=f"ドラフト {'あり' if draft_ok else 'なし'}",
            improvement_point=None if draft_ok else "顧客向け回答ドラフトの本文を補完し、結論と案内を明確にしてください。",
        ))
        compliance_ok = bool(state.get("compliance_review_passed"))
        evaluations.append(AgentEvaluation(
            agent_name="ComplianceReviewerAgent",
            is_good=compliance_ok,
            detail=f"レビュー {'通過' if compliance_ok else '未通過'}",
            improvement_point=None if compliance_ok else "レビュー差戻し論点を反映し、回答内容を再点検してください。",
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


def _build_overall_summary(state: CaseState, agent_scores: list[AgentEvaluation]) -> str:
    if bool(state.get("escalation_required")):
        return "調査は一定の成果を出したものの、確実な回答に必要な材料が不足しており、エスカレーション判断は妥当です。"
    if bool(state.get("compliance_review_passed")):
        return "主要エージェントの出力は概ね有効で、顧客向け回答とレビューは完了しています。継続改善点は各エージェント別評価を参照してください。"
    weak_count = sum(1 for item in agent_scores if not item.is_good)
    return f"自動実行は完了しましたが、{weak_count} 件の改善余地があります。差戻し論点とエージェント別評価を確認してください。"


def _build_improvement_points(state: CaseState, agent_scores: list[AgentEvaluation]) -> list[str]:
    items = [item.improvement_point for item in agent_scores if item.improvement_point]
    if bool(state.get("escalation_required")):
        items.append("エスカレーション先で追加確認すべき観点を整理し、引き継ぎ情報を過不足なく記載してください。")
    elif not bool(state.get("compliance_review_passed")):
        items.append("最終回答前にレビュー差戻し事項を解消し、顧客向け表現を再確認してください。")
    deduplicated: list[str] = []
    for item in items:
        if item not in deduplicated:
            deduplicated.append(item)
    return deduplicated


def _calculate_overall_score(state: CaseState, agent_scores: list[AgentEvaluation]) -> int:
    score = 100
    score -= sum(12 for item in agent_scores if not item.is_good)
    if bool(state.get("escalation_required")):
        score -= 10
    if not bool(state.get("compliance_review_passed")) and not bool(state.get("escalation_required")):
        score -= 8
    return max(0, min(100, score))


def _format_agent_evaluation(evaluation: AgentEvaluation) -> str:
    return f"{evaluation.agent_name}: {'good' if evaluation.is_good else 'needs improvement'} - {evaluation.detail}"


def _report_item(label: str, value: Any, description: str) -> list[str]:
    return [
        f"- {label}: {value}",
        f"  説明: {description}",
    ]