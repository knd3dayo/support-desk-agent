from __future__ import annotations

import asyncio
import inspect
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import BACK_SUPPORT_INQUIRY_WRITER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload


@dataclass(slots=True)
class BackSupportInquiryWriterPhaseExecutor:
    write_shared_memory_tool: Callable[..., Any]
    write_draft_tool: Callable[..., Any] | None = None

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
        result = tool(*args)
        if inspect.isawaitable(result):
            try:
                resolved = asyncio.run(cast(Coroutine[Any, Any, Any], result))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    resolved = loop.run_until_complete(result)
                finally:
                    loop.close()
            return str(resolved)
        return str(result)

    def execute(self, state: Mapping[str, Any]) -> dict[str, Any]:
        update = dict(state)
        case_id = str(update.get("case_id") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        escalation_reason = str(update.get("escalation_reason") or "調査結果だけでは確実な回答が困難")
        missing_artifacts = list(update.get("escalation_missing_artifacts") or [])
        requested_items = "、".join(missing_artifacts) if missing_artifacts else "追加ログおよび再現情報"

        if str(update.get("execution_mode") or "") == "plan":
            escalation_draft = (
                "plan モードでは通常回答の代わりにエスカレーション案を返します。"
                f" 理由: {escalation_reason}。依頼予定項目: {requested_items}。"
            )
        else:
            escalation_draft = (
                "現時点では確実な回答に必要な情報が不足しているため、バックサポートへエスカレーションします。"
                f" 調査継続のため、{requested_items} の提供をご確認ください。"
            )

        if case_id and workspace_path:
            context_payload: SharedMemoryDocumentPayload = {
                "title": "Back Support Inquiry Draft",
                "heading_level": 2,
                "bullets": [
                    f"Escalation draft: {escalation_draft}",
                    f"Requested artifacts: {requested_items}",
                ],
            }
            progress_payload: SharedMemoryDocumentPayload = {
                "title": "Back Support Inquiry Draft",
                "heading_level": 2,
                "bullets": [
                    "Current phase: escalation_draft_ready",
                    "Owner: BackSupportInquiryWriterAgent",
                    "Next phase: wait_for_approval",
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
            if self.write_draft_tool is not None:
                draft_payload: SharedMemoryDocumentPayload = {
                    "title": "Back Support Inquiry Draft",
                    "heading_level": 1,
                    "summary": escalation_draft,
                    "bullets": [f"Requested artifacts: {requested_items}"],
                }
                self._invoke_tool(self.write_draft_tool, case_id, workspace_path, draft_payload, "replace")

        return {
            "current_agent": BACK_SUPPORT_INQUIRY_WRITER_AGENT,
            "escalation_draft": escalation_draft,
            "draft_response": escalation_draft,
        }


def build_back_support_inquiry_writer_agent_definition() -> AgentDefinition:
    return AgentDefinition(
        BACK_SUPPORT_INQUIRY_WRITER_AGENT,
        "Write escalation inquiry drafts for users and back support",
        kind="agent",
        parent_role=SUPERVISOR_AGENT,
    )