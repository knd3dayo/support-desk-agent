from __future__ import annotations

from support_ope_agents.workflow.state import WorkflowKind


WORKFLOW_LABELS: dict[WorkflowKind, str] = {
    "specification_inquiry": "仕様調査ワークフロー",
    "incident_investigation": "障害調査ワークフロー",
    "ambiguous_case": "判定困難ワークフロー",
}


def route_workflow(prompt: str) -> WorkflowKind:
    normalized = prompt.lower()

    spec_keywords = (
        "仕様",
        "仕様確認",
        "expected",
        "期待動作",
        "design",
        "behavior",
    )
    incident_keywords = (
        "障害",
        "エラー",
        "落ちる",
        "停止",
        "incident",
        "failure",
        "exception",
        "不具合",
    )
    ambiguous_keywords = (
        "仕様か",
        "不具合か",
        "判断",
        "切り分け",
        "どちら",
        "想定通りか",
    )

    if any(keyword in normalized for keyword in ambiguous_keywords):
        return "ambiguous_case"
    if any(keyword in normalized for keyword in incident_keywords):
        return "incident_investigation"
    if any(keyword in normalized for keyword in spec_keywords):
        return "specification_inquiry"
    return "ambiguous_case"


def build_plan_steps(workflow_kind: WorkflowKind) -> list[str]:
    if workflow_kind == "specification_inquiry":
        return [
            "問い合わせ内容から仕様確認ポイントを抽出する",
            "関連ナレッジと既知仕様を確認する",
            "サポート担当者向けの仕様説明ドラフトを作成する",
        ]
    if workflow_kind == "incident_investigation":
        return [
            "問い合わせ内容と workspace から障害兆候を把握する",
            "ログ解析とナレッジ探索を並列で実施する",
            "原因仮説と暫定対応を統合して回答ドラフトを作成する",
        ]
    return [
        "仕様か不具合かの判定観点を整理する",
        "仕様調査と障害調査の両観点で情報を集める",
        "判定結果と次アクションを整理して回答ドラフトを作成する",
    ]


def summarize_plan(workflow_kind: WorkflowKind) -> str:
    label = WORKFLOW_LABELS[workflow_kind]
    return f"SuperVisorAgent は {label} を選択し、plan モードの結果を承認後に action モードへ引き継ぐ。"