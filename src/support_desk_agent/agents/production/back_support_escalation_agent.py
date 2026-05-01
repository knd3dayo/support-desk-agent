from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any, Callable, Mapping, cast

from langgraph.graph import END, START, StateGraph

from support_desk_agent.agents.abstract_agent import AbstractAgent
from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.agents.roles import BACK_SUPPORT_ESCALATION_AGENT, SUPERVISOR_AGENT
from support_desk_agent.util.asyncio_utils import run_awaitable_sync
from support_desk_agent.util.shared_memory_payload import SharedMemoryDocumentPayload

if TYPE_CHECKING:
    from support_desk_agent.models.state import CaseState, as_state_dict


@dataclass(slots=True)
class BackSupportEscalationPhaseExecutor(AbstractAgent):
    read_shared_memory_tool: Callable[..., Any]
    write_shared_memory_tool: Callable[..., Any]

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
        result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(cast(Any, result))
            return str(resolved)
        return str(result)

    @staticmethod
    def _parse_memory(raw_result: str) -> dict[str, str]:
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return {"context": "", "progress": "", "summary": ""}
        if not isinstance(parsed, dict):
            return {"context": "", "progress": "", "summary": ""}
        return {
            "context": str(parsed.get("context") or ""),
            "progress": str(parsed.get("progress") or ""),
            "summary": str(parsed.get("summary") or ""),
        }

    def execute(self, state: Mapping[str, Any]) -> dict[str, Any]:
        update = as_state_dict(state)
        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        memory_snapshot = {"context": "", "progress": "", "summary": ""}
        if case_id and workspace_path:
            memory_snapshot = self._parse_memory(self._invoke_tool(self.read_shared_memory_tool, case_id, workspace_path))

        escalation_reason = str(update.get("escalation_reason") or "調査結果だけでは確実な回答が困難")
        investigation_summary = str(update.get("investigation_summary") or "")
        missing_artifacts = list(update.get("escalation_missing_artifacts") or [])
        if not missing_artifacts and memory_snapshot["progress"].strip():
            missing_artifacts = ["追加ログおよび再現情報"]

        escalation_summary = str(update.get("escalation_summary") or "").strip()
        if not escalation_summary:
            escalation_summary = f"エスカレーション理由: {escalation_reason}"
            if investigation_summary:
                escalation_summary += f" 調査要約: {investigation_summary}"
            if missing_artifacts:
                escalation_summary += f" 追加で必要な資料: {', '.join(missing_artifacts)}"

        if case_id and workspace_path:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Back Support Escalation",
                "heading_level": 2,
                "bullets": [
                    f"Escalation reason: {escalation_reason}",
                    f"Escalation summary: {escalation_summary}",
                    f"Missing artifacts: {', '.join(missing_artifacts) if missing_artifacts else 'n/a'}",
                ],
            }
            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Back Support Escalation",
                "heading_level": 2,
                "bullets": [
                    "Current phase: escalation_preparation",
                    "Owner: BackSupportEscalationAgent",
                    "Next phase: inquiry_draft",
                ],
            }
            self._invoke_tool(
                self.write_shared_memory_tool,
                case_id,
                workspace_path,
                context_payload,
                progress_payload,
                None,
                "append",
            )

        return {
            "escalation_required": True,
            "escalation_reason": escalation_reason,
            "escalation_summary": escalation_summary,
            "escalation_missing_artifacts": missing_artifacts,
            "current_agent": BACK_SUPPORT_ESCALATION_AGENT,
        }

    def create_node(self):
        from support_desk_agent.models.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node(
            "back_support_escalation",
            lambda state: cast("CaseState", self.execute(cast(dict[str, Any], state))),
        )
        graph.add_edge(START, "back_support_escalation")
        graph.add_edge("back_support_escalation", END)
        return graph.compile()

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            BACK_SUPPORT_ESCALATION_AGENT,
            "Organize evidence and missing artifacts for back support escalation",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_back_support_escalation_agent_definition() -> AgentDefinition:
        return BackSupportEscalationPhaseExecutor.build_agent_definition()
