from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from support_desk_agent.models.state import as_state_dict

if TYPE_CHECKING:
    from support_desk_agent.models.state import CaseState

from support_desk_agent.agents.roles import APPROVAL_AGENT
from support_desk_agent.agents.roles import INTAKE_AGENT
from support_desk_agent.agents.roles import SUPERVISOR_AGENT
from support_desk_agent.agents.roles import TICKET_UPDATE_AGENT


class CaseStatuses:
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    DRAFT_READY = "DRAFT_READY"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_CUSTOMER_INPUT = "WAITING_CUSTOMER_INPUT"
    CLOSED = "CLOSED"


class ReportStatusTriggers:
    WAITING_APPROVAL = "waiting_approval"
    CLOSED = "closed"
    BY_STATUS = {
        CaseStatuses.WAITING_APPROVAL: WAITING_APPROVAL,
        CaseStatuses.CLOSED: CLOSED,
    }


class NextActionTexts:
    PLAN_APPROVAL = "この計画で action を実行するか確認してください。"
    ESCALATION_APPROVAL = "エスカレーション問い合わせ文案を確認し、送付可否を承認してください。"
    DRAFT_APPROVAL = "回答ドラフトを確認し、チケット更新を承認してください。"
    PROVIDE_INTAKE_INPUT = "IntakeAgent の質問に回答し、追加情報を提供してください。"
    RESUME_INTAKE = "追加情報を反映して Intake subgraph を再実行する"
    EXECUTE_TICKET_UPDATE = "外部チケット更新内容を確定して更新を実行する"
    COMPLETE_TICKET_UPDATE = "外部チケット更新を完了しました"
    START_SUPERVISOR_INVESTIGATION = "SuperVisorAgent が調査フェーズを開始する"
    REEVALUATE_WITH_CUSTOMER_INPUT = "追加情報を踏まえて SuperVisorAgent が再評価する"
    PRESENT_PLAN_FOR_APPROVAL = "ユーザーに計画を提示して承認を得る"
    SAMPLE_PREPARE_ESCALATION = "BackSupportEscalationAgent が問い合わせ文案を準備する"
    SAMPLE_PREPARE_DRAFT_FOR_APPROVAL = "SuperVisorAgent がドラフトを整えて承認待ちに進める"
    SAMPLE_ESCALATION_TO_APPROVAL = "エスカレーション問い合わせ文案を承認待ちに進める"
    APPROVAL_REVIEW_DRAFT = "ApprovalAgent へドラフトを回付する"
    PRODUCTION_PREPARE_ESCALATION = "BackSupportEscalationAgent がエスカレーション材料を整理する"
    PRODUCTION_START_DRAFT_PHASE = "SuperVisorAgent がドラフト作成フェーズを開始する"
    PRODUCTION_ESCALATION_TO_APPROVAL = "エスカレーション問い合わせ文案を承認フェーズへ回付する"


class StateTransitionHelper:
    @staticmethod
    def supervisor_investigating(
        state: "CaseState" | Mapping[str, Any],
        *,
        current_agent: str = SUPERVISOR_AGENT,
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["status"] = CaseStatuses.INVESTIGATING
        update["current_agent"] = current_agent
        return update

    @staticmethod
    def draft_ready(
        state: "CaseState" | Mapping[str, Any],
        *,
        current_agent: str | None = None,
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["status"] = CaseStatuses.DRAFT_READY
        if current_agent is not None:
            update["current_agent"] = current_agent
        return update

    @staticmethod
    def intake_triaged(
        state: "CaseState" | Mapping[str, Any],
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["status"] = CaseStatuses.TRIAGED
        update["current_agent"] = INTAKE_AGENT
        return update

    @staticmethod
    def waiting_for_customer_input(
        state: "CaseState" | Mapping[str, Any],
        *,
        next_action: str = NextActionTexts.PROVIDE_INTAKE_INPUT,
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["status"] = CaseStatuses.WAITING_CUSTOMER_INPUT
        update["current_agent"] = INTAKE_AGENT
        if not update.get("next_action"):
            update["next_action"] = next_action
        return update

    @staticmethod
    def waiting_for_approval(
        state: "CaseState" | Mapping[str, Any],
        *,
        current_agent: str = APPROVAL_AGENT,
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["status"] = CaseStatuses.WAITING_APPROVAL
        update["current_agent"] = current_agent
        update.setdefault("approval_decision", "pending")
        if update.get("execution_mode") == "plan":
            update["next_action"] = NextActionTexts.PLAN_APPROVAL
        elif update.get("escalation_required"):
            update["next_action"] = NextActionTexts.ESCALATION_APPROVAL
        else:
            update["next_action"] = NextActionTexts.DRAFT_APPROVAL
        return update

    @staticmethod
    def ticket_update_prepared(
        state: "CaseState" | Mapping[str, Any],
        *,
        payload: str,
        next_action: str,
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["current_agent"] = TICKET_UPDATE_AGENT
        update["ticket_update_payload"] = payload
        update["next_action"] = next_action
        return update

    @staticmethod
    def ticket_update_completed(
        state: "CaseState" | Mapping[str, Any],
        *,
        result_message: str = "Zendesk と Redmine の更新処理を完了しました。",
        next_action: str = NextActionTexts.COMPLETE_TICKET_UPDATE,
    ) -> dict[str, Any]:
        update = as_state_dict(state)
        update["status"] = CaseStatuses.CLOSED
        update["current_agent"] = TICKET_UPDATE_AGENT
        update["ticket_update_result"] = result_message
        update["next_action"] = next_action
        return update