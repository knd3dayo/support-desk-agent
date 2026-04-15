from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, cast

from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.intake_agent import IntakeAgent
from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.runtime.asyncio_utils import run_awaitable_sync
from support_ope_agents.tools.shared_memory_payload import SharedMemoryDocumentPayload

if TYPE_CHECKING:
    from support_ope_agents.agents.draft_writer_agent import DraftWriterPhaseExecutor
    from support_ope_agents.agents.knowledge_retriever_agent import KnowledgeRetrieverPhaseExecutor
    from support_ope_agents.agents.log_analyzer_agent import LogAnalyzerPhaseExecutor
    from support_ope_agents.workflow.state import CaseState


@dataclass(slots=True)
class InvestigatePhaseExecutor:
    read_shared_memory_tool: Callable[..., Any] | None = None
    write_shared_memory_tool: Callable[..., Any] | None = None
    log_analyzer_executor: "LogAnalyzerPhaseExecutor | None" = None
    knowledge_retriever_executor: "KnowledgeRetrieverPhaseExecutor | None" = None
    draft_writer_executor: "DraftWriterPhaseExecutor | None" = None

    def _invoke_tool(self, tool: Callable[..., Any], *args: object) -> str:
        result = tool(*args)
        if inspect.isawaitable(result):
            resolved = run_awaitable_sync(cast(Any, result))
            return str(resolved)
        return str(result)

    @staticmethod
    def _merge_unique_lines(base_text: str, extra_text: str) -> str:
        normalized_base = base_text.strip()
        normalized_extra = extra_text.strip()
        if not normalized_base:
            return normalized_extra
        if not normalized_extra or normalized_extra in normalized_base:
            return normalized_base
        return f"{normalized_base} 追加調査: {normalized_extra}".strip()

    @staticmethod
    def _select_final_knowledge_source(results: list[dict[str, object]]) -> str:
        matched = [item for item in results if str(item.get("status") or "") == "matched"]
        if not matched:
            return ""
        document_results = [item for item in matched if str(item.get("source_type") or "") == "document_source"]
        selected = document_results[0] if document_results else matched[0]
        return str(selected.get("source_name") or "").strip()

    @staticmethod
    def _build_investigation_summary(
        *,
        workflow_kind: str,
        raw_issue: str,
        log_analysis_summary: str,
        knowledge_retrieval_summary: str,
        final_source: str,
    ) -> str:
        if workflow_kind == "specification_inquiry":
            if knowledge_retrieval_summary:
                return knowledge_retrieval_summary
            return f"問い合わせ対象の仕様確認を進めています。対象: {raw_issue}".strip()
        parts = [part for part in [log_analysis_summary, knowledge_retrieval_summary] if part.strip()]
        if parts:
            summary = " ".join(parts)
            if final_source:
                summary = f"{summary} 採用した根拠ソース: {final_source}。"
            return summary.strip()
        return f"ログと関連資料の両面から調査を進めています。対象: {raw_issue}".strip()

    def _write_shared_memory(self, state: "CaseState") -> None:
        if self.write_shared_memory_tool is None:
            return
        case_id = str(state.get("case_id") or "").strip()
        workspace_path = str(state.get("workspace_path") or "").strip()
        if not case_id or not workspace_path:
            return
        context_payload: SharedMemoryDocumentPayload = {
            "title": "Investigate Agent Result",
            "heading_level": 2,
            "bullets": [
                f"Workflow kind: {str(state.get('workflow_kind') or 'n/a')}",
                f"Log analysis summary: {str(state.get('log_analysis_summary') or 'n/a')}",
                f"Knowledge retrieval summary: {str(state.get('knowledge_retrieval_summary') or 'n/a')}",
                f"Investigation summary: {str(state.get('investigation_summary') or 'n/a')}",
            ],
        }
        progress_payload: SharedMemoryDocumentPayload = {
            "title": "Investigate Agent Result",
            "heading_level": 2,
            "bullets": [
                "Current phase: INVESTIGATING",
                f"Draft generated: {'yes' if str(state.get('draft_response') or '').strip() else 'no'}",
                f"Final knowledge source: {str(state.get('knowledge_retrieval_final_adopted_source') or 'n/a')}",
            ],
        }
        summary_payload: SharedMemoryDocumentPayload = {
            "title": "Investigate Agent Result",
            "heading_level": 2,
            "bullets": [
                f"Summary: {str(state.get('investigation_summary') or 'n/a')}",
                f"Next action: {str(state.get('next_action') or 'n/a')}",
            ],
        }
        self._invoke_tool(
            self.write_shared_memory_tool,
            case_id,
            workspace_path,
            context_payload,
            progress_payload,
            summary_payload,
            "append",
        )

    def execute(self, state: "CaseState") -> "CaseState":
        update = cast("CaseState", dict(state))
        update["status"] = "INVESTIGATING"
        update["current_agent"] = INVESTIGATE_AGENT

        workflow_kind = IntakeAgent.resolve_effective_workflow_kind(
            update,
            {"context": "", "progress": "", "summary": ""},
        )
        log_analysis_summary = str(update.get("log_analysis_summary") or "")
        log_analysis_file = str(update.get("log_analysis_file") or "")
        if self.log_analyzer_executor is not None and workflow_kind != "specification_inquiry":
            log_result = self.log_analyzer_executor.execute(update)
            log_analysis_summary = self._merge_unique_lines(log_analysis_summary, str(log_result.get("summary") or ""))
            log_analysis_file = str(log_result.get("file") or log_analysis_file)
            if log_analysis_summary:
                update["log_analysis_summary"] = log_analysis_summary
            if log_analysis_file:
                update["log_analysis_file"] = log_analysis_file

        knowledge_retrieval_summary = str(update.get("knowledge_retrieval_summary") or "")
        knowledge_retrieval_results = cast(list[dict[str, object]], update.get("knowledge_retrieval_results") or [])
        knowledge_retrieval_adopted_sources = cast(list[str], update.get("knowledge_retrieval_adopted_sources") or [])
        if self.knowledge_retriever_executor is not None:
            knowledge_result = self.knowledge_retriever_executor.execute(update)
            knowledge_retrieval_summary = self._merge_unique_lines(
                knowledge_retrieval_summary,
                str(knowledge_result.get("knowledge_retrieval_summary") or ""),
            )
            raw_results = knowledge_result.get("knowledge_retrieval_results")
            if isinstance(raw_results, list):
                knowledge_retrieval_results = [item for item in raw_results if isinstance(item, dict)]
            raw_sources = knowledge_result.get("knowledge_retrieval_adopted_sources")
            if isinstance(raw_sources, list):
                knowledge_retrieval_adopted_sources = [str(item) for item in raw_sources if str(item).strip()]
            update["knowledge_retrieval_summary"] = knowledge_retrieval_summary
            update["knowledge_retrieval_results"] = knowledge_retrieval_results
            update["knowledge_retrieval_adopted_sources"] = knowledge_retrieval_adopted_sources

        final_source = self._select_final_knowledge_source(knowledge_retrieval_results)
        if final_source:
            update["knowledge_retrieval_final_adopted_source"] = final_source

        if not str(update.get("investigation_summary") or "").strip():
            update["investigation_summary"] = self._build_investigation_summary(
                workflow_kind=workflow_kind,
                raw_issue=str(update.get("raw_issue") or ""),
                log_analysis_summary=log_analysis_summary,
                knowledge_retrieval_summary=knowledge_retrieval_summary,
                final_source=final_source,
            )

        if self.draft_writer_executor is not None and update.get("execution_mode") != "plan":
            draft_result = self.draft_writer_executor.execute(cast(dict[str, object], update))
            update["draft_response"] = str(draft_result.get("draft_response") or update.get("draft_response") or "")

        update["next_action"] = "SuperVisorAgent が調査結果を確認し、承認またはエスカレーションへ進める"
        self._write_shared_memory(update)
        return update

    @staticmethod
    def build_investigate_agent_definition() -> AgentDefinition:
        return AgentDefinition(
            INVESTIGATE_AGENT,
            "Investigate the case, gather evidence, and prepare a support-facing draft",
            kind="agent",
            parent_role=SUPERVISOR_AGENT,
        )