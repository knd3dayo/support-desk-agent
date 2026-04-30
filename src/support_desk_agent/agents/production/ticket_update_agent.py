from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import TYPE_CHECKING, Any, Callable, cast

from langgraph.graph import END, START, StateGraph

from support_desk_agent.agents.abstract_agent import AbstractAgent
from support_desk_agent.agents.agent_definition import AgentDefinition
from support_desk_agent.agents.roles import SUPERVISOR_AGENT, TICKET_UPDATE_AGENT
from support_desk_agent.config.models import AppConfig, TicketServerBindingSettings
from support_desk_agent.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_desk_agent.runtime.case_id_resolver import CaseIdResolverService
from support_desk_agent.util.asyncio_utils import run_awaitable_sync
from support_desk_agent.tools.mcp_client import McpToolClient
from support_desk_agent.util.langchain import build_chat_openai_model
from support_desk_agent.util.parsing import McpToolSelectionDecision, parse_mcp_tool_selection_xml

if TYPE_CHECKING:
    from support_desk_agent.models.state import CaseState


@dataclass(slots=True)
class TicketUpdateAgent(AbstractAgent):
    config: AppConfig
    prepare_ticket_update_tool: Callable[..., Any]
    zendesk_reply_tool: Callable[..., Any]
    redmine_update_tool: Callable[..., Any]
    ticket_mcp_client: McpToolClient | None = None

    def _invoke_tool(self, tool: Callable[..., Any], *args: object, **kwargs: object) -> str:
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
        return self.config.tools.ticket_sources.get(ticket_kind)

    def _build_ticket_tool_prompt(
        self,
        *,
        ticket_kind: str,
        ticket_id: str,
        binding: TicketServerBindingSettings,
        tools_xml: str,
    ) -> str:
        static_arguments = json.dumps(binding.arguments, ensure_ascii=False, sort_keys=True)
        description = binding.description or f"{ticket_kind} ticket lookup"
        return (
            "あなたは ticket 更新直前の TicketUpdateAgent です。\n"
            "これから MCP server 配下のツール一覧を見て、更新対象 ticket の現在状態を取得する tool を選択してください。\n"
            "tool 名は必ず一覧に存在するものだけを使ってください。推測や創作は禁止です。\n"
            "get_tool は必須です。list_tool は ticket が見つからない場合の候補提示用です。不要なら skip にしてください。\n"
            "attachment_tool は不要なら skip にしてください。\n"
            "戻り値は XML のみで、説明文やコードフェンスを付けないでください。\n"
            "\n"
            f"期待する XML タグ名: <{binding.decision_tag}>...</{binding.decision_tag}>\n"
            f"ticket kind: {ticket_kind}\n"
            f"ticket id: {ticket_id}\n"
            f"server name: {binding.server}\n"
            f"server purpose: {description}\n"
            f"static arguments: {static_arguments}\n"
            "available tools:\n"
            f"{tools_xml}\n"
        )

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
    def _lookup_context_text(state: CaseState) -> str:
        parts = [
            str(state.get("user_issue") or "").strip(),
            str(state.get("draft_response") or "").strip(),
            str(state.get("escalation_draft") or "").strip(),
        ]
        summaries = cast(dict[str, str], state.get("intake_ticket_context_summary") or {})
        parts.extend(str(value).strip() for value in summaries.values() if str(value).strip())
        return "\n".join(part for part in parts if part)

    def _lookup_ticket_context(self, *, state: CaseState, ticket_kind: str, ticket_id: str) -> tuple[str | None, tuple[str, str] | None]:
        binding = self._ticket_binding(ticket_kind)
        if binding is None or not binding.enabled or self.ticket_mcp_client is None:
            return None, None
        if not ticket_id:
            return None, None

        model = build_chat_openai_model(self.config)
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
        decision = self._parse_tool_decision(str(getattr(response, "content", response)), decision_tag=binding.decision_tag)
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

    def _compose_payload(self, state: CaseState) -> str:
        intake_ticket_summaries = dict(cast(dict[str, str], state.get("intake_ticket_context_summary") or {}))
        ticket_followup_questions: dict[str, str] = {}

        for ticket_kind in ("external", "internal"):
            ticket_key = f"{ticket_kind}_ticket"
            ticket_id = str(state.get(f"{ticket_kind}_ticket_id") or "").strip()
            looked_up_summary, candidate_question = self._lookup_ticket_context(
                state=state,
                ticket_kind=ticket_kind,
                ticket_id=ticket_id,
            )
            if looked_up_summary:
                intake_ticket_summaries[ticket_key] = looked_up_summary
            if candidate_question is not None:
                field_name, question = candidate_question
                ticket_followup_questions[field_name] = question

        prepared = self._invoke_tool(
            self.prepare_ticket_update_tool,
            draft_response=str(state.get("draft_response") or "").strip(),
            escalation_draft=str(state.get("escalation_draft") or "").strip(),
            external_ticket_id=str(state.get("external_ticket_id") or "").strip(),
            internal_ticket_id=str(state.get("internal_ticket_id") or "").strip(),
            intake_ticket_context_summary=intake_ticket_summaries,
            ticket_followup_questions=ticket_followup_questions,
        )
        try:
            parsed = json.loads(prepared)
        except json.JSONDecodeError:
            return prepared.strip()
        payload = str(parsed.get("payload") or "").strip() if isinstance(parsed, dict) else ""
        return payload or prepared.strip()

    def prepare_update(self, state: CaseState) -> CaseState:
        return cast(
            "CaseState",
            StateTransitionHelper.ticket_update_prepared(
                state,
                payload=self._compose_payload(state),
                next_action=NextActionTexts.EXECUTE_TICKET_UPDATE,
            ),
        )

    def execute_update(self, state: CaseState) -> CaseState:
        return cast("CaseState", StateTransitionHelper.ticket_update_completed(state))

    def create_node(self):
        from support_desk_agent.models.state import CaseState

        graph = StateGraph(CaseState)
        graph.add_node("ticket_update_prepare", self.prepare_update)
        graph.add_node("ticket_update_execute", self.execute_update)
        graph.add_edge(START, "ticket_update_prepare")
        graph.add_edge("ticket_update_prepare", "ticket_update_execute")
        graph.add_edge("ticket_update_execute", END)
        return graph.compile()

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
        return TicketUpdateAgent.build_agent_definition()