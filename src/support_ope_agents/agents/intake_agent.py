from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.memory import CaseMemoryStore

if TYPE_CHECKING:
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class IntakePhaseExecutor:
    memory_store: CaseMemoryStore

    def execute(self, state: CaseState) -> CaseState:
        update = dict(state)
        update["status"] = "TRIAGED"
        update["current_agent"] = INTAKE_AGENT

        raw_issue = str(update.get("raw_issue") or "").strip()
        if raw_issue:
            update.setdefault("masked_issue", raw_issue)

        workspace_path = str(update.get("workspace_path") or "").strip()
        case_id = str(update.get("case_id") or "").strip()
        if workspace_path and case_id:
            case_paths = self.memory_store.initialize_case(case_id, workspace_path=workspace_path)
            context_lines = [
                "# Shared Context",
                "",
                f"- Case ID: {case_id}",
            ]
            trace_id = str(update.get("trace_id") or "").strip()
            if trace_id:
                context_lines.append(f"- Trace ID: {trace_id}")
            if raw_issue:
                context_lines.extend([
                    "- Intake Summary:",
                    f"  - Raw issue: {raw_issue}",
                    f"  - Masked issue: {str(update.get('masked_issue') or raw_issue)}",
                ])
            case_paths.shared_context.write_text("\n".join(context_lines) + "\n", encoding="utf-8")

            progress_lines = [
                "# Shared Progress",
                "",
                "- Current status: TRIAGED",
                "- Next phase: INVESTIGATING",
            ]
            if update.get("execution_mode") == "plan":
                progress_lines.append("- Planning note: plan モードのため、次はユーザー承認待ちの案内を行う")
            case_paths.shared_progress.write_text("\n".join(progress_lines) + "\n", encoding="utf-8")

        if update.get("execution_mode") == "plan":
            update["next_action"] = "ユーザーに計画を提示して承認を得る"
        else:
            update["next_action"] = "SuperVisorAgent が調査フェーズを開始する"
        return cast("CaseState", update)


def build_intake_agent_definition() -> AgentDefinition:
    return AgentDefinition(INTAKE_AGENT, "Triage and initialize the case", kind="phase", parent_role=SUPERVISOR_AGENT)