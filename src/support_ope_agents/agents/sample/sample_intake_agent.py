from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.config.models import TicketCandidateMatchingSettings, TicketServerBindingSettings
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.tools.mcp_xml_toolset import XmlMcpToolsetProvider
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.util.parsing import McpToolSelectionDecision, parse_mcp_tool_selection_xml
from support_ope_agents.models.state import CaseState


class SampleIntakeClassification(BaseModel):
    category: str = Field(default="ambiguous_case")
    urgency: str = Field(default="medium")
    investigation_focus: str = Field(default="問い合わせ内容の事実関係を確認する")
    reason: str = Field(default="")

@dataclass(slots=True)
class SampleIntakeAgent(AbstractAgent):
    config: AppConfig
    ticket_mcp_provider: XmlMcpToolsetProvider | None = None

    @staticmethod
    def _default_issue() -> str:
        return "ログインできず、昨日の夕方から 500 エラーが発生しているため確認してください。"

    def _build_classification_prompt(self, raw_issue: str) -> str:
        return (
            "あなたは問い合わせ受付の最小サンプル IntakeAgent です。\n"
            "問い合わせを以下の schema に従って分類してください。\n"
            "- category: specification_inquiry / incident_investigation / ambiguous_case のいずれか\n"
            "- urgency: low / medium / high / critical のいずれか\n"
            "- investigation_focus: 調査で最初に確認すべき観点\n"
            "- reason: 分類理由\n"
            f"問い合わせ本文:\n{raw_issue}"
        )

    def _build_ticket_tool_prompt(
        self,
        *,
        ticket_kind: str,
        raw_issue: str,
        ticket_id: str,
        binding: TicketServerBindingSettings,
        tools_xml: str,
    ) -> str:
        static_arguments = json.dumps(binding.arguments, ensure_ascii=False, sort_keys=True)
        description = binding.description or f"{ticket_kind} ticket lookup"
        return (
            "あなたは問い合わせ受付の最小サンプル IntakeAgent です。\n"
            "これから MCP server 配下のツール一覧を見て、チケット取得に使う tool 群を選択してください。\n"
            "tool 名は必ず一覧に存在するものだけを使ってください。推測や創作は禁止です。\n"
            "get_tool は必須です。list_tool は ticket が見つからない場合の候補提示用です。\n"
            "もし添付ファイル取得ツールもあれば、それも attachment_tool として選択してください。無ければ skip にしてください。\n"
            "戻り値は XML のみで、説明文やコードフェンスを付けないでください。\n"
            "\n"
            "期待する XML 形式:\n"
            "<decision>\n"
            "  <get_tool>tool_name</get_tool>\n"
            "  <get_arguments>{\"key\": \"value\"}</get_arguments>\n"
            "  <list_tool>tool_name_or_skip</list_tool>\n"
            "  <list_arguments>{\"key\": \"value\"}</list_arguments>\n"
            "  <get_attachment_tool>tool_name_or_skip</get_attachment_tool>\n"
            "  <get_attachment_arguments>{\"key\": \"value\"}</get_attachment_arguments>\n"
            "  <reason>selection reason</reason>\n"
            "</decision>\n"
            "\n"
            f"ticket kind: {ticket_kind}\n"
            f"ticket id: {ticket_id}\n"
            f"server name: {binding.server}\n"
            f"server purpose: {description}\n"
            f"static arguments: {static_arguments}\n"
            f"customer issue:\n{raw_issue}\n"
            "\n"
            "available tools:\n"
            f"{tools_xml}\n"
            "\n"
            "明示 ticket id がある場合は、その ticket を直接取得できるツールを get_tool に、候補提示できる一覧・検索系ツールを list_tool に設定してください。"
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

    def _ticket_binding(self, ticket_kind: str) -> TicketServerBindingSettings | None:
        return self.config.agents.IntakeAgent.ticket_servers.get(ticket_kind)

    @staticmethod
    def _artifact_dir(workspace_path: str) -> Path:
        return Path(workspace_path).expanduser().resolve() / ".artifacts" / "intake"

    def _summarize_ticket_payload(self, raw_result: str) -> str:
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            return raw_result.strip()
        if not isinstance(parsed, dict):
            return raw_result.strip()
        summary_parts = [
            str(parsed.get("title") or "").strip(),
            str(parsed.get("state") or parsed.get("status") or "").strip(),
            str(parsed.get("body") or parsed.get("summary") or "").strip(),
        ]
        return "\n".join(part for part in summary_parts if part) or raw_result.strip()

    def _write_ticket_artifact(self, *, workspace_path: str, ticket_kind: str, raw_result: str) -> list[str]:
        artifact_dir = self._artifact_dir(workspace_path)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            path = artifact_dir / f"{ticket_kind}_ticket.json"
            path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return [str(path)]
        path = artifact_dir / f"{ticket_kind}_ticket.txt"
        path.write_text(raw_result, encoding="utf-8")
        return [str(path)]

    def _write_attachment_artifact(self, *, workspace_path: str, ticket_kind: str, raw_result: str) -> list[str]:
        artifact_dir = self._artifact_dir(workspace_path)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            path = artifact_dir / f"{ticket_kind}_ticket_attachments.json"
            path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return [str(path)]
        path = artifact_dir / f"{ticket_kind}_ticket_attachments.txt"
        path.write_text(raw_result, encoding="utf-8")
        return [str(path)]

    @staticmethod
    def _first_present_value(item: dict[str, Any], field_names: list[str]) -> str:
        for field_name in field_names:
            value = str(item.get(field_name) or "").strip()
            if value:
                return value
        return ""

    def _candidate_label(self, *, item: dict[str, Any], matching: TicketCandidateMatchingSettings) -> str:
        number = self._first_present_value(item, matching.candidate_id_fields)
        title = self._first_present_value(item, matching.candidate_text_fields)
        state = str(item.get("state") or item.get("status") or "").strip()
        parts = [part for part in [number, title, state] if part]
        return " / ".join(parts)

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
        matching: TicketCandidateMatchingSettings,
        ticket_id: str,
        raw_issue: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
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

    def _extract_candidate_items(self, raw_result: str) -> list[dict[str, Any]]:
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
            matching=matching,
            ticket_id=ticket_id,
            raw_issue=raw_issue,
            candidates=candidates,
        )
        if not ranked_candidates:
            return None
        labels = [
            self._candidate_label(item=item, matching=matching)
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

    def _lookup_ticket_candidates(
        self,
        *,
        ticket_kind: str,
        raw_issue: str,
        ticket_id: str,
        binding: TicketServerBindingSettings,
        decision: McpToolSelectionDecision,
    ) -> tuple[str, str] | None:
        provider = self.ticket_mcp_provider
        if provider is None:
            return None
        if decision.list_tool_name.lower() == "skip":
            return None
        raw_result = provider.call_tool(
            binding.server,
            decision.list_tool_name,
            decision.list_arguments or {},
            static_arguments=binding.arguments,
        )
        return self._candidate_followup_question(
            binding=binding,
            ticket_kind=ticket_kind,
            ticket_id=ticket_id,
            raw_issue=raw_issue,
            raw_result=raw_result,
        )

    def hydrate_ticket_contexts(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        if self.ticket_mcp_provider is None:
            return update

        raw_issue = str(update.get("raw_issue") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        if not raw_issue or not workspace_path:
            return update

        ticket_summaries = cast(dict[str, str], update.get("intake_ticket_context_summary") or {})
        ticket_artifacts = cast(dict[str, list[str]], update.get("intake_ticket_artifacts") or {})
        followup_questions = cast(dict[str, str], update.get("intake_followup_questions") or {})
        agent_errors = cast(list[dict[str, str]], update.get("agent_errors") or [])
        model = build_chat_openai_model(self.config, temperature=0)
        provider = self.ticket_mcp_provider
        if provider is None:
            return update

        for ticket_kind in ("external", "internal"):
            ticket_id = str(update.get(f"{ticket_kind}_ticket_id") or "").strip()
            lookup_enabled = bool(update.get(f"{ticket_kind}_ticket_lookup_enabled"))
            if not ticket_id or not lookup_enabled:
                continue

            binding = self._ticket_binding(ticket_kind)
            if binding is None or not binding.enabled:
                update[f"{ticket_kind}_ticket_lookup_enabled"] = False
                continue

            decision: McpToolSelectionDecision | None = None
            try:
                tools_xml = provider.render_tools_xml(binding.server)
                
                response = model.invoke(
                    [
                        HumanMessage(
                            content=self._build_ticket_tool_prompt(
                                ticket_kind=ticket_kind,
                                raw_issue=raw_issue,
                                ticket_id=ticket_id,
                                binding=binding,
                                tools_xml=tools_xml,
                            )
                        )
                    ]
                )
                decision = self._parse_tool_decision(self._extract_text(response), decision_tag=binding.decision_tag)
                raw_result = provider.call_tool(
                    binding.server,
                    decision.get_tool_name,
                    decision.get_arguments,
                    static_arguments=binding.arguments,
                )
                ticket_summaries[f"{ticket_kind}_ticket"] = self._summarize_ticket_payload(raw_result)
                ticket_artifacts[f"{ticket_kind}_ticket"] = self._write_ticket_artifact(
                    workspace_path=workspace_path,
                    ticket_kind=ticket_kind,
                    raw_result=raw_result,
                )
                if decision.attachment_tool_name.lower() != "skip":
                    attachment_result = provider.call_tool(
                        binding.server,
                        decision.attachment_tool_name,
                        decision.attachment_arguments or {},
                        static_arguments=binding.arguments,
                    )
                    ticket_summaries[f"{ticket_kind}_ticket_attachments"] = "Attachment metadata retrieved."
                    ticket_artifacts[f"{ticket_kind}_ticket_attachments"] = self._write_attachment_artifact(
                        workspace_path=workspace_path,
                        ticket_kind=ticket_kind,
                        raw_result=attachment_result,
                    )
            except Exception as error:
                update[f"{ticket_kind}_ticket_lookup_enabled"] = False
                if self._is_not_found_error(error):
                    try:
                        if decision is None:
                            raise ValueError("ticket tool selection was not produced before fallback")
                        candidate_question = self._lookup_ticket_candidates(
                            ticket_kind=ticket_kind,
                            raw_issue=raw_issue,
                            ticket_id=ticket_id,
                            binding=binding,
                            decision=decision,
                        )
                        if candidate_question is not None:
                            field_name, question = candidate_question
                            followup_questions[field_name] = question
                            ticket_summaries[f"{ticket_kind}_ticket"] = question
                            continue
                    except Exception as candidate_error:
                        agent_errors.append(
                            {
                                "agent": "SampleIntakeAgent",
                                "phase": f"{ticket_kind}_ticket_candidates",
                                "message": str(candidate_error),
                            }
                        )
                agent_errors.append(
                    {
                        "agent": "SampleIntakeAgent",
                        "phase": f"{ticket_kind}_ticket_lookup",
                        "message": str(error),
                    }
                )

        update["intake_ticket_context_summary"] = ticket_summaries
        update["intake_ticket_artifacts"] = ticket_artifacts
        update["intake_followup_questions"] = followup_questions
        update["agent_errors"] = agent_errors
        return update

    def prepare_state(self, state: dict[str, Any]) -> dict[str, Any]:
        raw_issue = str(state.get("raw_issue") or "").strip()
        return StateTransitionHelper.intake_triaged(state, masked_issue=raw_issue)

    def classify_issue(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        raw_issue = str(update.get("raw_issue") or "").strip()
        if not raw_issue:
            return update

        model = build_chat_openai_model(self.config)
        structured_model = model.with_structured_output(SampleIntakeClassification)
        response = structured_model.invoke(
            [
                HumanMessage(content=self._build_classification_prompt(raw_issue)),
            ]
        )
        if isinstance(response, SampleIntakeClassification):
            classification = response
        elif isinstance(response, dict):
            classification = SampleIntakeClassification.model_validate(response)
        elif hasattr(response, "model_dump"):
            classification = SampleIntakeClassification.model_validate(response.model_dump())
        else:
            raise ValueError("SampleIntakeAgent returned an unsupported structured output payload.")

        update["intake_category"] = classification.category
        update["intake_urgency"] = classification.urgency
        update["intake_investigation_focus"] = classification.investigation_focus
        update["intake_classification_reason"] = classification.reason
        return update

    def finalize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        if update.get("intake_followup_questions"):
            update = StateTransitionHelper.waiting_for_customer_input(
                update,
                next_action="チケット候補をユーザーへ確認し、正しい ticket id を回答してもらう",
            )
            return update
        update["next_action"] = NextActionTexts.START_SUPERVISOR_INVESTIGATION
        return update

    def run_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        update = self.prepare_state(state)
        update = self.classify_issue(update)
        update = self.hydrate_ticket_contexts(update)
        return self.finalize_state(update)

    def create_node(self) -> Any:
        graph = StateGraph(CaseState)
        graph.add_node("intake_prepare", lambda state: cast(CaseState, self.prepare_state(cast(dict[str, Any], state))))
        graph.add_node("intake_classify", lambda state: cast(CaseState, self.classify_issue(cast(dict[str, Any], state))))
        graph.add_node("intake_mcp_tickets", lambda state: cast(CaseState, self.hydrate_ticket_contexts(cast(dict[str, Any], state))))
        graph.add_node("intake_finalize", lambda state: cast(CaseState, self.finalize_state(cast(dict[str, Any], state))))
        graph.add_edge(START, "intake_prepare")
        graph.add_edge("intake_prepare", "intake_classify")
        graph.add_edge("intake_classify", "intake_mcp_tickets")
        graph.add_edge("intake_mcp_tickets", "intake_finalize")
        graph.add_edge("intake_finalize", END)
        return graph.compile()

    def execute(self, *, raw_issue: str) -> dict[str, Any]:
        node = self.create_node()
        return dict(node.invoke({"raw_issue": raw_issue}))

    @classmethod
    def build_agent_definition(cls) -> AgentDefinition:
        return AgentDefinition(
            INTAKE_AGENT,
            "Triage and initialize the case",
            kind="phase",
            parent_role=SUPERVISOR_AGENT,
        )

    @staticmethod
    def build_intake_agent_definition() -> AgentDefinition:
        return SampleIntakeAgent.build_agent_definition()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the sample intake agent")
    parser.add_argument("issue", nargs="?", default=SampleIntakeAgent._default_issue(), help="Customer issue text")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    args = parser.parse_args()

    config = load_config(args.config)
    agent = SampleIntakeAgent(config=config)
    result = agent.execute(raw_issue=args.issue)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())