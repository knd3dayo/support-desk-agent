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
    agent_scores = _evaluate_agents(state)
    checklist_section = _render_checklist(checklist or [], state, context_text, progress_text, summary_text)
    overall_evaluation = _build_overall_evaluation(state, agent_scores)

    report_lines = [
        f"# Support Improvement Report: {case_id}",
        "",
        "## Meta",
        f"- Case ID: {case_id}",
        f"- Trace ID: {trace_id}",
        f"- Workspace: {case_paths.root}",
        f"- Final status: {str(state.get('status') or 'unknown')}",
        "",
        "## 問い合わせ内容",
        str(state.get("raw_issue") or "n/a"),
        "",
        "## 調査に使用したログ・成果物",
        *([f"- {path}" for path in artifact_paths] or ["- なし"]),
        "",
        "## 結果と評価",
        f"- 結果: {_result_label(state)}",
        f"- 調査要約: {str(state.get('investigation_summary') or 'n/a')}",
        f"- コンプライアンス要約: {str(state.get('compliance_review_summary') or 'n/a')}",
        f"- エスカレーション理由: {str(state.get('escalation_reason') or 'n/a')}",
        "",
        "## エージェント呼び出しシーケンス",
        "```mermaid",
        sequence_diagram,
        "```",
        "",
        "## エージェント別評価",
        *[f"- {line}" for line in agent_scores],
        "",
        "## ユーザー指定チェックリスト",
        *checklist_section,
        "",
        "## Shared Memory Snapshot",
        "### Context",
        context_text.strip() or "n/a",
        "",
        "### Progress",
        progress_text.strip() or "n/a",
        "",
        "### Summary",
        summary_text.strip() or "n/a",
        "",
        "## 総合評価",
        overall_evaluation,
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


def _evaluate_agents(state: CaseState) -> list[str]:
    evaluations: list[str] = []
    intake_ok = bool(state.get("intake_category")) and not bool(state.get("intake_rework_required"))
    evaluations.append(f"IntakeAgent: {'good' if intake_ok else 'needs improvement'} - 分類と前処理 {'完了' if intake_ok else '要再確認'}")
    workflow_kind = str(state.get("workflow_kind") or "")
    if workflow_kind in {"incident_investigation", "ambiguous_case"}:
        log_ok = bool(str(state.get("log_analysis_summary") or "").strip())
        evaluations.append(f"LogAnalyzerAgent: {'good' if log_ok else 'needs improvement'} - ログ解析結果 {'あり' if log_ok else 'なし'}")
    knowledge_ok = bool(list(state.get("knowledge_retrieval_adopted_sources") or []))
    evaluations.append(f"KnowledgeRetrieverAgent: {'good' if knowledge_ok else 'needs improvement'} - 採用ナレッジソース {', '.join(list(state.get('knowledge_retrieval_adopted_sources') or [])) or 'なし'}")
    if bool(state.get("escalation_required")):
        escalation_ok = bool(str(state.get("escalation_summary") or "").strip()) and bool(str(state.get("escalation_draft") or "").strip())
        evaluations.append(f"BackSupportEscalationAgent: {'good' if escalation_ok else 'needs improvement'} - エスカレーション要約 {'あり' if escalation_ok else 'なし'}")
        evaluations.append(f"BackSupportInquiryWriterAgent: {'good' if escalation_ok else 'needs improvement'} - 問い合わせ文案 {'あり' if escalation_ok else 'なし'}")
    else:
        draft_ok = bool(str(state.get("draft_response") or "").strip())
        evaluations.append(f"DraftWriterAgent: {'good' if draft_ok else 'needs improvement'} - ドラフト {'あり' if draft_ok else 'なし'}")
        compliance_ok = bool(state.get("compliance_review_passed"))
        evaluations.append(f"ComplianceReviewerAgent: {'good' if compliance_ok else 'needs improvement'} - レビュー {'通過' if compliance_ok else '未通過'}")
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


def _build_overall_evaluation(state: CaseState, agent_scores: list[str]) -> str:
    if bool(state.get("escalation_required")):
        return "調査は一定の成果を出したものの、確実な回答に必要な材料が不足しており、エスカレーション判断は妥当です。"
    if bool(state.get("compliance_review_passed")):
        return "主要エージェントの出力は概ね有効で、顧客向け回答とレビューは完了しています。継続改善点は各エージェント別評価を参照してください。"
    weak_count = sum(1 for item in agent_scores if "needs improvement" in item)
    return f"自動実行は完了しましたが、{weak_count} 件の改善余地があります。差戻し論点とエージェント別評価を確認してください。"