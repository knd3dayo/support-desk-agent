from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, TypedDict, cast

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import SUPERVISOR_AGENT, TICKET_UPDATE_AGENT
from support_ope_agents.config.models import AppConfig, TicketServerBindingSettings
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.runtime.case_id_resolver import CaseIdResolverService
from support_ope_agents.util.asyncio_utils import run_awaitable_sync
from support_ope_agents.tools.mcp_client import McpToolClient
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.parsing import McpToolSelectionDecision, parse_mcp_tool_selection_xml


class SampleTicketUpdateState(TypedDict, total=False):
    status: str
    current_agent: str
    ticket_update_payload: str
    ticket_update_result: str
    next_action: str
    draft_response: str
    escalation_draft: str



class SampleTicketUpdateAgent(AbstractAgent):
    def __init__(self, tool_registry: "ToolRegistry"):
        self.tool_registry = tool_registry

    def _invoke_tool(self, tool: Any, *args: object, **kwargs: object) -> str:
        try:
            result = tool(*args, **kwargs)
        except TypeError:
            if kwargs:
                try:
                    signature = inspect.signature(tool)
                    filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
                    result = tool(*args, **filtered_kwargs)
                except (TypeError, ValueError):
                    result = tool(*args)
            else:
                result = tool(*args)
        if inspect.isawaitable(result):
            return str(run_awaitable_sync(cast(Any, result)))
        return str(result)

    def _ticket_binding(self, ticket_kind: str) -> TicketServerBindingSettings | None:
        if self.config is None:
            return None
        return self.config.tools.ticket_sources.get(ticket_kind)

    def _build_ticket_tool_prompt(self, *, ticket_kind: str, ticket_id: str, binding: TicketServerBindingSettings, tools_xml: str) -> str:
        static_arguments = json.dumps(binding.arguments, ensure_ascii=False, sort_keys=True)
        description = binding.description or f"{ticket_kind} ticket lookup"
        return (
            "あなたは sample TicketUpdateAgent です。\n"
            "ticket 更新前に現在状態を取得する MCP tool を選択してください。\n"
            "get_tool は必須です。list_tool は ticket が見つからない場合の候補提示用です。不要なら skip にしてください。\n"
            "attachment_tool は不要なら skip にしてください。\n"
            "戻り値は XML のみで返してください。\n"
            f"期待する XML タグ名: <{binding.decision_tag}>...</{binding.decision_tag}>\n"
            f"ticket kind: {ticket_kind}\n"
            f"ticket id: {ticket_id}\n"
            f"server name: {binding.server}\n"
            f"server purpose: {description}\n"
            f"static arguments: {static_arguments}\n"
            f"available tools:\n{tools_xml}\n"
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        if isinstance(response, AIMessage):
            return str(response.content)
        if hasattr(response, "content"):
            return str(getattr(response, "content"))
        return str(response)

    @staticmethod
    def _parse_tool_decision(raw_text: str, *, decision_tag: str = "decision") -> McpToolSelectionDecision:
        return parse_mcp_tool_selection_xml(raw_text, decision_tag=decision_tag)

    @staticmethod
    def _build_ticket_summary(parsed: dict[str, object], raw_result: str) -> str:
        for key in ("summary", "message", "title", "subject", "description", "body"):
            value = str(parsed.get(key) or "").strip()
            if value:
                return value
        payload = {key: value for key, value in parsed.items() if key != "attachments"}
        if payload:
            return json.dumps(payload, ensure_ascii=False)
        return raw_result

    @staticmethod
    def _normalize_similarity_text(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z]+", "", value).lower()

    @classmethod
    def _ticket_id_similarity_for_fields(
        cls,
        *,
        expected_ticket_id: str,
        candidate: dict[str, Any],
        field_names: list[str],
    ) -> float:
        expected = cls._normalize_similarity_text(expected_ticket_id)
        if not expected:
            return 0.0
        ratios = []
        for field_name in field_names:
            value = str(candidate.get(field_name) or "")
            normalized = cls._normalize_similarity_text(value)
            if not normalized:
                continue
            ratios.append(SequenceMatcher(None, expected, normalized).ratio())
        return max(ratios, default=0.0)

    @staticmethod
    def _text_tokens(value: str) -> set[str]:
        lowered = value.lower()
        tokens = set(re.findall(r"[0-9a-z_\-]{2,}", lowered))
        if tokens:
            return tokens
        compact = re.sub(r"\s+", "", lowered)
        if len(compact) < 2:
            return set()
        return {compact[index : index + 2] for index in range(len(compact) - 1)}

    @classmethod
    def _content_similarity_for_fields(
        cls,
        *,
        raw_issue: str,
        candidate: dict[str, Any],
        field_names: list[str],
    ) -> float:
        candidate_text = " ".join(str(candidate.get(field_name) or "").strip() for field_name in field_names).strip()
        if not candidate_text:
            return 0.0
        raw_tokens = cls._text_tokens(raw_issue)
        candidate_tokens = cls._text_tokens(candidate_text)
        overlap_score = 0.0
        if raw_tokens and candidate_tokens:
            overlap_score = len(raw_tokens & candidate_tokens) / max(len(raw_tokens), 1)
        sequence_score = SequenceMatcher(None, raw_issue.lower(), candidate_text.lower()).ratio()
        return max(overlap_score, sequence_score)

    @classmethod
    def _rank_ticket_candidates(
        cls,
        *,
        binding: TicketServerBindingSettings,
        ticket_id: str,
        raw_issue: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matching = binding.candidate_matching
        scored: list[tuple[float, float, dict[str, Any]]] = []
        for candidate in candidates:
            id_score = cls._ticket_id_similarity_for_fields(
                expected_ticket_id=ticket_id,
                candidate=candidate,
                field_names=matching.candidate_id_fields,
            )
            content_score = cls._content_similarity_for_fields(
                raw_issue=raw_issue,
                candidate=candidate,
                field_names=matching.candidate_text_fields,
            )
            combined_score = (id_score * 0.55) + (content_score * 0.45)
            if (
                id_score >= matching.min_id_similarity
                or content_score >= matching.min_content_similarity
                or combined_score >= matching.min_combined_similarity
            ):
                scored.append((combined_score, id_score, candidate))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [candidate for _, _, candidate in scored]

    @staticmethod
    def _extract_candidate_items(raw_result: str) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            for key in ("items", "issues", "results"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _first_present_value(item: dict[str, Any], field_names: list[str]) -> str:
        for field_name in field_names:
            value = str(item.get(field_name) or "").strip()
            if value:
                return value
        return ""

    def _candidate_label(self, *, item: dict[str, Any], binding: TicketServerBindingSettings) -> str:
        matching = binding.candidate_matching
        number = self._first_present_value(item, matching.candidate_id_fields)
        title = self._first_present_value(item, matching.candidate_text_fields)
        state = str(item.get("state") or item.get("status") or "").strip()
        parts = [part for part in [number, title, state] if part]
        return " / ".join(parts)

    def _candidate_followup_question(
        self,
        *,
        binding: TicketServerBindingSettings,
        ticket_kind: str,
        ticket_id: str,
        raw_issue: str,
        raw_result: str,
    ) -> tuple[str, str] | None:
        candidates = self._extract_candidate_items(raw_result)
        if not candidates:
            return None
        matching = binding.candidate_matching
        ranked_candidates = self._rank_ticket_candidates(
            binding=binding,
            ticket_id=ticket_id,
            raw_issue=raw_issue,
            candidates=candidates,
        )
        if not ranked_candidates:
            return None
        labels = [
            self._candidate_label(item=item, binding=binding)
            for item in ranked_candidates[: matching.max_question_candidates]
        ]
        labels = [label for label in labels if label]
        if not labels:
            return None
        field_name = f"{ticket_kind}_ticket_confirmation"
        question = (
            f"指定された {ticket_kind} ticket id '{ticket_id}' は見つかりませんでした。"
            f" このチケットですか？ 候補: {' | '.join(labels)}"
        )
        return field_name, question

    @staticmethod
    def _is_not_found_error(error: Exception) -> bool:
        normalized = str(error).lower()
        return any(token in normalized for token in ["not found", "404", "issue not found"])

    @staticmethod
    def _lookup_context_text(state: dict[str, Any]) -> str:
        parts = [
            str(state.get("user_issue") or "").strip(),
            str(state.get("draft_response") or "").strip(),
            str(state.get("escalation_draft") or "").strip(),
        ]
        summaries = cast(dict[str, str], state.get("intake_ticket_context_summary") or {})
        parts.extend(str(value).strip() for value in summaries.values() if str(value).strip())
        return "\n".join(part for part in parts if part)

    def _lookup_ticket_context(self, *, state: dict[str, Any], ticket_kind: str, ticket_id: str) -> tuple[str | None, tuple[str, str] | None]:
        if self.config is None or self.ticket_mcp_client is None:
            return None, None
        binding = self._ticket_binding(ticket_kind)
        if binding is None or not binding.enabled or not ticket_id or self._is_auto_generated_ticket_id(ticket_kind, ticket_id):
            return None, None
        model = build_chat_openai_model(self.config, temperature=0)
        tools_xml = self.ticket_mcp_client.render_tools_xml(binding.server)
        response = model.invoke(
            [
                {
                    "role": "user",
                    "content": self._build_ticket_tool_prompt(
                        ticket_kind=ticket_kind,
                        ticket_id=ticket_id,
                        binding=binding,
                        tools_xml=tools_xml,
                    ),
                }
            ]
        )
        decision = self._parse_tool_decision(self._extract_text(response), decision_tag=binding.decision_tag)
        available_tool_names = self.ticket_mcp_client.list_tool_names(binding.server)
        if decision.get_tool_name not in available_tool_names:
            raise ValueError(f"selected MCP tool does not exist: {decision.get_tool_name}")
        if decision.list_tool_name.lower() != "skip" and decision.list_tool_name not in available_tool_names:
            raise ValueError(f"selected MCP tool does not exist: {decision.list_tool_name}")
        raw_issue = self._lookup_context_text(state)
        try:
            raw_result = self.ticket_mcp_client.call_tool(
                binding.server,
                decision.get_tool_name,
                decision.get_arguments,
                static_arguments=binding.arguments,
            )
        except Exception as error:
            if self._is_not_found_error(error) and decision.list_tool_name.lower() != "skip":
                try:
                    list_raw_result = self.ticket_mcp_client.call_tool(
                        binding.server,
                        decision.list_tool_name,
                        decision.list_arguments or {},
                        static_arguments=binding.arguments,
                    )
                    candidate_question = self._candidate_followup_question(
                        binding=binding,
                        ticket_kind=ticket_kind,
                        ticket_id=ticket_id,
                        raw_issue=raw_issue,
                        raw_result=list_raw_result,
                    )
                    return None, candidate_question
                except Exception:
                    pass
            raise
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return raw_result.strip() or None, None
        if isinstance(parsed, dict):
            return self._build_ticket_summary(parsed, raw_result), None
        return raw_result.strip() or None, None

    def _compose_payload(self, state: dict[str, Any]) -> str:
        ticket_summaries = dict(cast(dict[str, str], state.get("intake_ticket_context_summary") or {}))
        ticket_followup_questions: dict[str, str] = {}

        for ticket_kind in ("external", "internal"):
            ticket_id = str(state.get(f"{ticket_kind}_ticket_id") or "").strip()
            looked_up_summary, candidate_question = self._lookup_ticket_context(
                state=state,
                ticket_kind=ticket_kind,
                ticket_id=ticket_id,
            )
            if looked_up_summary:
                ticket_summaries[f"{ticket_kind}_ticket"] = looked_up_summary
            if candidate_question is not None:
                field_name, question = candidate_question
                ticket_followup_questions[field_name] = question

        tools = {t.name: t.handler for t in self.tool_registry.get_tools(TICKET_UPDATE_AGENT)}
        prepare_ticket_update_tool = tools.get("prepare_ticket_update")
        if prepare_ticket_update_tool is None:
            return ""
        prepared = self._invoke_tool(
            prepare_ticket_update_tool,
            draft_response=str(state.get("draft_response") or "").strip(),
            escalation_draft=str(state.get("escalation_draft") or "").strip(),
            external_ticket_id=str(state.get("external_ticket_id") or "").strip(),
            internal_ticket_id=str(state.get("internal_ticket_id") or "").strip(),
            intake_ticket_context_summary=ticket_summaries,
            ticket_followup_questions=ticket_followup_questions,
        )
        try:
            parsed = json.loads(prepared)
        except json.JSONDecodeError:
            return prepared.strip()
        payload = str(parsed.get("payload") or "").strip() if isinstance(parsed, dict) else ""
        return payload or prepared.strip()

    def prepare_update(self, state: dict[str, Any]) -> dict[str, Any]:
        draft_response = str(state.get("draft_response") or "").strip()
        escalation_draft = str(state.get("escalation_draft") or "").strip()
        payload = self._compose_payload(state)
        if escalation_draft:
            return StateTransitionHelper.ticket_update_prepared(
                state,
                payload=payload,
                next_action="問い合わせ文案を確定して外部連携を実行する",
            )
        if draft_response:
            return StateTransitionHelper.ticket_update_prepared(
                state,
                payload=payload,
                next_action="回答内容を確定してチケット更新を実行する",
            )
        return StateTransitionHelper.ticket_update_prepared(
            state,
            payload=payload,
            next_action=NextActionTexts.EXECUTE_TICKET_UPDATE,
        )

    def execute_update(self, state: dict[str, Any]) -> dict[str, Any]:
        return StateTransitionHelper.ticket_update_completed(state)

    def create_node(self) -> Any:
        graph = StateGraph(SampleTicketUpdateState)
        graph.add_node(
            "ticket_update_prepare",
            lambda state: cast(SampleTicketUpdateState, self.prepare_update(cast(dict[str, Any], state))),
        )
        graph.add_node(
            "ticket_update_execute",
            lambda state: cast(SampleTicketUpdateState, self.execute_update(cast(dict[str, Any], state))),
        )
        graph.add_edge(START, "ticket_update_prepare")
        graph.add_edge("ticket_update_prepare", "ticket_update_execute")
        graph.add_edge("ticket_update_execute", END)
        return graph.compile()

    def execute(
        self,
        *,
        draft_response: str = "",
        escalation_draft: str = "",
    ) -> dict[str, Any]:
        node = self.create_node()
        return dict(
            node.invoke(
                {
                    "draft_response": draft_response,
                    "escalation_draft": escalation_draft,
                }
            )
        )

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            TICKET_UPDATE_AGENT,
            "Prepare and execute ticket updates after approval",
            kind="phase",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_ticket_update_agent_definition() -> AgentDefinition:
        return SampleTicketUpdateAgent.build_agent_definition()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample ticket update agent")
    parser.add_argument("--draft-response", default="", help="Draft reply to reflect in the outgoing ticket update")
    parser.add_argument("--escalation-draft", default="", help="Escalation draft to reflect in the outgoing ticket update")
    args = parser.parse_args()

    agent = SampleTicketUpdateAgent()
    result = agent.execute(
        draft_response=args.draft_response,
        escalation_draft=args.escalation_draft,
    )
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())