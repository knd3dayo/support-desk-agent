from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT
from support_ope_agents.util.formatting import format_result

if TYPE_CHECKING:
    from support_ope_agents.agents.sample.sample_back_support_escalation_agent import SampleBackSupportEscalationAgent
    from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class SampleSupervisorAgent(AbstractAgent):
    investigate_executor: "SampleInvestigateAgent | None" = None
    back_support_escalation_executor: "SampleBackSupportEscalationAgent | None" = None

    @staticmethod
    def route_after_investigation(state: dict[str, object]) -> str:
        if state.get("escalation_required"):
            return "escalation_review"
        return "draft_review"

    @staticmethod
    def route_entry(state: dict[str, object]) -> str:
        decision = str(state.get("approval_decision") or "").strip().lower()
        if decision in {"rejected", "reject"}:
            return "draft_review"
        return "investigation"

    @staticmethod
    def _should_escalate(state: dict[str, Any]) -> bool:
        if bool(state.get("escalation_required")):
            return True
        raw_issue = str(state.get("raw_issue") or "").lower()
        escalation_markers = ("escalate", "escalation", "エスカレーション", "バックサポート", "unsupported")
        return any(marker in raw_issue for marker in escalation_markers)

    @staticmethod
    def _fallback_investigation_summary(raw_issue: str) -> str:
        if raw_issue:
            return f"サンプル調査結果: 問い合わせ内容を確認しました。要点は「{raw_issue}」です。"
        return "サンプル調査結果: 問い合わせ内容を確認しました。"

    def _build_draft_response(self, investigation_summary: str) -> str:
        summary = investigation_summary.strip() or "サンプル調査を実行しました。"
        return f"お問い合わせありがとうございます。\n\n{summary}\n\n必要であれば追加の確認事項もご案内できます。"

    def execute_investigation(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", dict(state))
        update["status"] = "INVESTIGATING"
        update["current_agent"] = SUPERVISOR_AGENT

        raw_issue = str(update.get("raw_issue") or "").strip()
        investigation_summary = str(update.get("investigation_summary") or "").strip()
        if not investigation_summary:
            if self.investigate_executor is not None and raw_issue:
                try:
                    investigation_result = self.investigate_executor.execute(query=raw_issue)
                    investigation_summary = format_result(investigation_result)
                except Exception:
                    investigation_summary = self._fallback_investigation_summary(raw_issue)
            else:
                investigation_summary = self._fallback_investigation_summary(raw_issue)

        update["investigation_summary"] = investigation_summary
        update["escalation_required"] = self._should_escalate(cast(dict[str, Any], update))
        if update["escalation_required"]:
            update["escalation_reason"] = str(update.get("escalation_reason") or "追加確認のためバックサポートへ問い合わせます。")
            update["next_action"] = "BackSupportEscalationAgent が問い合わせ文案を準備する"
        else:
            update["escalation_reason"] = ""
            update["next_action"] = "SuperVisorAgent がドラフトを整えて承認待ちに進める"
        return update

    def execute_escalation_review(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", dict(state))
        update["status"] = "DRAFT_READY"
        if self.back_support_escalation_executor is not None:
            try:
                query = str(update.get("raw_issue") or "").strip() or None
                update.update(cast("CaseState", self.back_support_escalation_executor.execute(query=query)))
            except Exception:
                pass

        update["escalation_required"] = True
        update["escalation_reason"] = str(update.get("escalation_reason") or "追加確認のためバックサポートへ問い合わせます。")
        update["escalation_summary"] = str(
            update.get("escalation_summary")
            or f"サンプルエスカレーション要約: {str(update.get('investigation_summary') or '').strip() or '調査結果を確認してください。'}"
        )
        update["escalation_draft"] = str(
            update.get("escalation_draft")
            or "お世話になっております。追加調査のため、関連ログと再現条件のご確認をお願いいたします。"
        )
        update["draft_response"] = str(update.get("draft_response") or update["escalation_draft"])
        update["next_action"] = "エスカレーション問い合わせ文案を承認待ちに進める"
        return update

    def execute_draft_review(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", dict(state))
        update["status"] = "DRAFT_READY"
        update["current_agent"] = SUPERVISOR_AGENT
        update["review_focus"] = "サンプル回答として分かりやすいか確認する"
        update["draft_review_iterations"] = 1
        update["draft_review_max_loops"] = 1
        if not str(update.get("draft_response") or "").strip():
            update["draft_response"] = self._build_draft_response(str(update.get("investigation_summary") or ""))
        update["next_action"] = "ApprovalAgent へドラフトを回付する"
        return update

    def create_node(self) -> Any:
        from support_ope_agents.workflow.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("supervisor_entry", lambda state: cast(CaseState, dict(cast(dict[str, Any], state))))
        graph.add_node("investigation", self.execute_investigation)
        graph.add_node("draft_review", self.execute_draft_review)
        graph.add_node("escalation_review", self.execute_escalation_review)
        graph.add_edge(START, "supervisor_entry")
        graph.add_conditional_edges(
            "supervisor_entry",
            lambda state: self.route_entry(cast(dict[str, object], state)),
            {
                "investigation": "investigation",
                "draft_review": "draft_review",
            },
        )
        graph.add_conditional_edges(
            "investigation",
            lambda state: self.route_after_investigation(cast(dict[str, object], state)),
            {
                "escalation_review": "escalation_review",
                "draft_review": "draft_review",
            },
        )
        graph.add_edge("draft_review", END)
        graph.add_edge("escalation_review", END)
        return graph.compile()

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            SUPERVISOR_AGENT,
            "Coordinate sample investigation flow and decide whether escalation is needed",
            kind="supervisor",
        )
