from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
from xml.etree import ElementTree

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from support_ope_agents.agents.abstract_agent import AbstractAgent
from support_ope_agents.agents.agent_definition import AgentDefinition
from support_ope_agents.agents.roles import INTAKE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.loader import load_config
from support_ope_agents.config.models import AppConfig
from support_ope_agents.config.models import TicketServerBindingSettings
from support_ope_agents.models.state_transitions import NextActionTexts, StateTransitionHelper
from support_ope_agents.tools.mcp_client import McpToolClient
from support_ope_agents.util.formatting import format_result
from support_ope_agents.util.langchain import build_chat_openai_model
from support_ope_agents.util.log_time_range import apply_derived_log_extract_range
from support_ope_agents.models.state import CaseState


class SampleIntakeClassification(BaseModel):
    category: str = Field(default="ambiguous_case")
    urgency: str = Field(default="medium")
    investigation_focus: str = Field(default="問い合わせ内容の事実関係を確認する")
    reason: str = Field(default="")


class TicketLookupAgentResult(BaseModel):
    content: str = ""
    suggestion: str = ""
    next_action: str = ""
    attachment_urls: list[str] = Field(default_factory=list)



class SampleIntakeAgent(AbstractAgent):
    def __init__(self, config: Any):
        from support_ope_agents.tools.registry import ToolRegistry
        self.config = config
        self.tool_registry = ToolRegistry(config)

    _TICKET_REJECTION_MARKERS = (
        "違う",
        "違います",
        "別",
        "いいえ",
        "not",
        "no",
        "誤り",
    )

    @staticmethod
    def _default_issue() -> str:
        return "ログインできず、昨日の夕方から 500 エラーが発生しているため確認してください。"

    @staticmethod
    def _extract_incident_timeframe(text: str) -> str:
        patterns = (
            r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?\b",
            r"\b\d{4}/\d{1,2}/\d{1,2}(?:\s+\d{1,2}:\d{2})?\b",
            r"\b\d{1,2}:\d{2}\b",
            r"(今日|昨日|一昨日|今朝|昨夜|本日|昨日の夜|本日午前|本日午後|午前|午後|深夜|夕方|朝方)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip()
        return ""

    @staticmethod
    def _load_classification_prompt_template() -> str:
        template_path = Path(__file__).parent.parent.parent / "instructions" / "intake_classification_prompt.txt"
        return template_path.read_text(encoding="utf-8")

    def _build_classification_prompt(self, raw_issue: str) -> str:
        template = self._load_classification_prompt_template()
        return template.format(raw_issue=raw_issue)

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
            "渡された MCP tools を使って、指定された ticket URL または ticket identifier を取得してください。\n"
            "直接取得できない場合は、必要に応じて一覧・検索系 tool を使って候補を探してください。\n"
            "tool 名や引数は必ず利用可能な tool 定義に従ってください。推測や創作は禁止です。\n"
            "最終出力は XML のみで、説明文やコードフェンスを付けないでください。\n"
            "添付ファイル URL が取得できた場合は、その URL を <attachments><attachment>...</attachment></attachments> に列挙してください。\n"
            "次に取るべき制御は <next_action> で明示してください。許可される値は proceed / confirm_ticket / request_ticket_id です。\n"
            "- proceed: ticket を特定できており、追加確認なしで後続処理へ進めてよい\n"
            "- confirm_ticket: ticket 候補の確認が必要\n"
            "- request_ticket_id: 正しい ticket URL または識別子の再入力が必要\n"
            "proceed の場合、<suggestion> は原則空にしてください。\n"
            "ticket 本文に title や body がある場合、content にはユーザーへそのまま説明できる粒度で要約を書いてください。\n"
            "特に issue body に『背景』『観測された問題』『期待する挙動』『改善候補』のような節がある場合は、それらを優先して短く要約してください。\n"
            "content には内部調査手順の一般論ではなく、その ticket 固有の内容を優先して書いてください。\n"
            "\n"
            "期待する XML 形式:\n"
            "<result>\n"
            "  <content>取得できた ticket の要約。取得できなければ空文字でも可</content>\n"
            "  <suggestion>次に取るべき行動。候補提示や確認事項があればここへ書く</suggestion>\n"
            "  <next_action>proceed | confirm_ticket | request_ticket_id</next_action>\n"
            "  <attachments>\n"
            "    <attachment>https://example.invalid/path/to/file</attachment>\n"
            "  </attachments>\n"
            "</result>\n"
            "\n"
            "出力例1: ticket を特定できて内容も取得できた場合\n"
            "<result>\n"
            "  <content>Issue #2 は、仕様問い合わせに対して直接回答できず shared memory 記録も欠落する問題です。背景として過去の改善レポートがあり、主な論点は『直接回答できていない』『shared memory に分類や緊急度が残っていない』『Supervisor の判断根拠が共有サマリーに残っていない』の3点です。期待する挙動は、仕様問い合わせへ直接回答し、構造化項目と判断根拠を shared memory に残すことです。</content>\n"
            "  <suggestion></suggestion>\n"
            "  <next_action>proceed</next_action>\n"
            "</result>\n"
            "\n"
            "出力例2: 候補確認が必要な場合\n"
            "<result>\n"
            "  <content>Issue #121 は Login failure incident、Issue #123 は Login 500 on production です。</content>\n"
            "  <suggestion>候補は Issue #121 または Issue #123 です。正しい ticket か確認してください。</suggestion>\n"
            "  <next_action>confirm_ticket</next_action>\n"
            "</result>\n"
            "\n"
            "出力例3: 再入力が必要な場合\n"
            "<result>\n"
            "  <content></content>\n"
            "  <suggestion>正しい ticket URL または識別子を教えてください。</suggestion>\n"
            "  <next_action>request_ticket_id</next_action>\n"
            "</result>\n"
            "\n"
            f"ticket kind: {ticket_kind}\n"
            f"ticket reference: {ticket_id}\n"
            f"server name: {binding.server}\n"
            f"server purpose: {description}\n"
            f"static arguments: {static_arguments}\n"
            f"customer issue:\n{raw_issue}\n"
            "\n"
            "available tools:\n"
            f"{tools_xml}\n"
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        if isinstance(response, AIMessage):
            return str(response.content)
        if hasattr(response, "content"):
            return str(getattr(response, "content"))
        return str(response)

    def _ticket_binding(self, ticket_kind: str) -> TicketServerBindingSettings | None:
        return self.config.tools.ticket_sources.get(ticket_kind)

    @staticmethod
    def _serialize_tool_result(raw_result: Any) -> str:
        if isinstance(raw_result, str):
            return raw_result
        if hasattr(raw_result, "model_dump"):
            return json.dumps(raw_result.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
        if isinstance(raw_result, (dict, list)):
            return json.dumps(raw_result, ensure_ascii=False)
        return str(raw_result)

    @staticmethod
    def _parse_ticket_lookup_result(raw_text: str) -> TicketLookupAgentResult:
        match = re.search(r"<result(?:\s[^>]*)?>.*?</result>", raw_text, flags=re.DOTALL)
        xml_text = match.group(0) if match else raw_text.strip()
        root = ElementTree.fromstring(xml_text)
        content_node = root.find("content")
        suggestion_node = root.find("suggestion")
        next_action_node = root.find("next_action")
        attachment_urls = [
            str(node.text or "").strip()
            for node in root.findall("./attachments/attachment")
            if str(node.text or "").strip()
        ]
        return TicketLookupAgentResult(
            content=str(content_node.text or "").strip() if content_node is not None else "",
            suggestion=str(suggestion_node.text or "").strip() if suggestion_node is not None else "",
            next_action=str(next_action_node.text or "").strip().lower() if next_action_node is not None else "",
            attachment_urls=attachment_urls,
        )

    def _run_ticket_lookup_agent(
        self,
        *,
        binding: TicketServerBindingSettings,
        ticket_kind: str,
        raw_issue: str,
        ticket_id: str,
    ) -> tuple[TicketLookupAgentResult, dict[str, Any]]:
        mcp_client = self.tools.ticket_mcp_client
        if mcp_client is None:
            raise ValueError("ticket MCP provider is not configured")
        model = build_chat_openai_model(self.config, temperature=0)
        tools_xml = mcp_client.render_tools_xml(binding.server)
        run_state: dict[str, Any] = {"tool_calls": []}
        tools = mcp_client.get_agent_tools(
            binding.server,
            static_arguments=binding.arguments,
            on_tool_call=run_state["tool_calls"].append,
        )
        agent = create_agent(
            model,
            tools,
            system_prompt=self._build_ticket_tool_prompt(
                ticket_kind=ticket_kind,
                raw_issue=raw_issue,
                ticket_id=ticket_id,
                binding=binding,
                tools_xml=tools_xml,
            ),
            name=f"sample_{ticket_kind}_ticket_lookup_agent",
        )
        result = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            f"ticket reference: {ticket_id}\n"
                            f"customer issue:\n{raw_issue}\n"
                            "該当 ticket を取得し、見つからなければ候補または次アクションを suggestion にまとめてください。"
                        )
                    )
                ]
            }
        )
        messages = result.get("messages") if isinstance(result, dict) else None
        final_message = messages[-1] if isinstance(messages, list) and messages else result
        parsed = self._parse_ticket_lookup_result(self._extract_text(final_message))
        return parsed, run_state

    @staticmethod
    def _artifact_dir(workspace_path: str) -> Path:
        return Path(workspace_path).expanduser().resolve() / ".artifacts" / "intake"

    @classmethod
    def _attachment_dir(cls, workspace_path: str, ticket_kind: str) -> Path:
        return cls._artifact_dir(workspace_path) / f"{ticket_kind}_attachments"

    @staticmethod
    def _attachment_filename_from_url(url: str, index: int) -> str:
        candidate = Path(unquote(urlparse(url).path)).name.strip()
        return candidate or f"attachment_{index}"

    def _download_ticket_attachments(
        self,
        *,
        workspace_path: str,
        ticket_kind: str,
        attachment_urls: list[str],
    ) -> list[str]:
        attachment_dir = self._attachment_dir(workspace_path, ticket_kind)
        attachment_dir.mkdir(parents=True, exist_ok=True)
        saved_paths: list[str] = []
        for index, url in enumerate(attachment_urls, start=1):
            target_path = attachment_dir / self._attachment_filename_from_url(url, index)
            if target_path.exists():
                target_path = attachment_dir / f"{target_path.stem}_{index}{target_path.suffix}"
            try:
                with urlopen(url, timeout=self.config.tools.download_timeout_seconds) as response:
                    target_path.write_bytes(response.read())
            except Exception:
                if not target_path.suffix:
                    target_path = target_path.with_suffix(".url")
                target_path.write_text(f"{url}\n", encoding="utf-8")
            saved_paths.append(str(target_path))
        return saved_paths

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

    @classmethod
    def _ticket_confirmation_answer(cls, state: dict[str, Any], ticket_kind: str) -> str:
        answers = cast(dict[str, Any], state.get("customer_followup_answers") or {})
        record = answers.get(f"{ticket_kind}_ticket_confirmation")
        if not isinstance(record, dict):
            return ""
        return str(record.get("answer") or "").strip()

    @classmethod
    def _answer_rejects_ticket_candidate(cls, answer: str) -> bool:
        normalized = answer.strip().lower()
        if not normalized:
            return False
        return any(marker in normalized for marker in cls._TICKET_REJECTION_MARKERS)

    def _resolve_ticket_followup_question(
        self,
        *,
        state: dict[str, Any],
        ticket_kind: str,
        lookup_result: TicketLookupAgentResult,
    ) -> str | None:
        suggestion = lookup_result.suggestion.strip()
        next_action = lookup_result.next_action.strip().lower()
        if next_action == "proceed":
            return None
        if not suggestion and next_action != "request_ticket_id":
            return None

        confirmation_answer = self._ticket_confirmation_answer(state, ticket_kind)
        if confirmation_answer and not self._answer_rejects_ticket_candidate(confirmation_answer):
            return None
        if confirmation_answer:
            return f"候補チケットは違うとのことなので、正しい {ticket_kind} ticket の URL または識別子を教えてください。"
        if next_action == "request_ticket_id":
            return suggestion or f"正しい {ticket_kind} ticket の URL または識別子を教えてください。"
        return suggestion

    def _hydrate_single_ticket_context(
        self,
        *,
        update: dict[str, Any],
        raw_issue: str,
        workspace_path: str,
        ticket_kind: str,
        ticket_summaries: dict[str, str],
        ticket_artifacts: dict[str, list[str]],
        followup_questions: dict[str, str],
        agent_errors: list[dict[str, str]],
    ) -> None:
        ticket_id = str(update.get(f"{ticket_kind}_ticket_id") or "").strip()
        lookup_enabled = bool(update.get(f"{ticket_kind}_ticket_lookup_enabled"))
        if not ticket_id or not lookup_enabled:
            return

        binding = self._ticket_binding(ticket_kind)
        if binding is None or not binding.enabled:
            update[f"{ticket_kind}_ticket_lookup_enabled"] = False
            return

        try:
            lookup_result, run_state = self._run_ticket_lookup_agent(
                binding=binding,
                ticket_kind=ticket_kind,
                raw_issue=raw_issue,
                ticket_id=ticket_id,
            )
            tool_calls = cast(list[dict[str, Any]], run_state.get("tool_calls") or [])
            artifact_paths = list(ticket_artifacts.get(f"{ticket_kind}_ticket") or [])
            if lookup_result.content:
                ticket_summaries[f"{ticket_kind}_ticket"] = lookup_result.content
                if tool_calls:
                    artifact_paths.extend(self._write_ticket_artifact(
                        workspace_path=workspace_path,
                        ticket_kind=ticket_kind,
                        raw_result=str(tool_calls[-1].get("raw_result") or lookup_result.content),
                    ))
            if lookup_result.attachment_urls:
                ticket_summaries[f"{ticket_kind}_ticket_attachments"] = "\n".join(lookup_result.attachment_urls)
                downloaded_paths = self._download_ticket_attachments(
                    workspace_path=workspace_path,
                    ticket_kind=ticket_kind,
                    attachment_urls=lookup_result.attachment_urls,
                )
                ticket_artifacts[f"{ticket_kind}_ticket_attachments"] = downloaded_paths
                artifact_paths.extend(downloaded_paths)
            if artifact_paths:
                ticket_artifacts[f"{ticket_kind}_ticket"] = artifact_paths

            followup_question = self._resolve_ticket_followup_question(
                state=update,
                ticket_kind=ticket_kind,
                lookup_result=lookup_result,
            )
            if followup_question:
                followup_questions[f"{ticket_kind}_ticket_confirmation"] = followup_question
            else:
                followup_questions.pop(f"{ticket_kind}_ticket_confirmation", None)

            if lookup_result.suggestion and not lookup_result.content:
                ticket_summaries[f"{ticket_kind}_ticket"] = lookup_result.suggestion
                update[f"{ticket_kind}_ticket_lookup_enabled"] = False
                return

            if not lookup_result.content and not lookup_result.suggestion:
                raise ValueError("ticket lookup agent returned neither content nor suggestion")
        except Exception as error:
            update[f"{ticket_kind}_ticket_lookup_enabled"] = False
            agent_errors.append(
                {
                    "agent": "SampleIntakeAgent",
                    "phase": f"{ticket_kind}_ticket_lookup",
                    "message": str(error),
                }
            )

    def hydrate_ticket_contexts(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        if self.tools.ticket_mcp_client is None:
            return update

        raw_issue = str(update.get("raw_issue") or "").strip()
        workspace_path = str(update.get("workspace_path") or "").strip()
        if not raw_issue or not workspace_path:
            return update

        ticket_summaries = cast(dict[str, str], update.get("intake_ticket_context_summary") or {})
        ticket_artifacts = cast(dict[str, list[str]], update.get("intake_ticket_artifacts") or {})
        followup_questions = cast(dict[str, str], update.get("intake_followup_questions") or {})
        agent_errors = cast(list[dict[str, str]], update.get("agent_errors") or [])

        for ticket_kind in ("external", "internal"):
            self._hydrate_single_ticket_context(
                update=update,
                raw_issue=raw_issue,
                workspace_path=workspace_path,
                ticket_kind=ticket_kind,
                ticket_summaries=ticket_summaries,
                ticket_artifacts=ticket_artifacts,
                followup_questions=followup_questions,
                agent_errors=agent_errors,
            )

        update["intake_ticket_context_summary"] = ticket_summaries
        update["intake_ticket_artifacts"] = ticket_artifacts
        update["intake_followup_questions"] = followup_questions
        update["agent_errors"] = agent_errors
        return update

    @staticmethod
    def route_after_ticket_followup_decision(state: dict[str, Any]) -> str:
        if state.get("intake_followup_questions"):
            return "request_customer_input"
        return "finalize"

    def request_customer_input(self, state: dict[str, Any]) -> dict[str, Any]:
        return StateTransitionHelper.waiting_for_customer_input(
            dict(state),
            next_action="チケット候補をユーザーへ確認し、正しい ticket id を回答してもらう",
        )

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
        extracted_timeframe = self._extract_incident_timeframe(raw_issue)
        existing_timeframe = str(update.get("intake_incident_timeframe") or "").strip()
        update["intake_incident_timeframe"] = extracted_timeframe or existing_timeframe
        apply_derived_log_extract_range(update, str(update.get("intake_incident_timeframe") or ""), config=self.config)
        return update

    def finalize_state(self, state: dict[str, Any]) -> dict[str, Any]:
        update = dict(state)
        update["next_action"] = NextActionTexts.START_SUPERVISOR_INVESTIGATION
        return update

    def create_node(self) -> Any:
        graph = StateGraph(CaseState)
        graph.add_node("intake_prepare", lambda state: cast(CaseState, self.prepare_state(cast(dict[str, Any], state))))
        graph.add_node("intake_classify", lambda state: cast(CaseState, self.classify_issue(cast(dict[str, Any], state))))
        graph.add_node("intake_mcp_tickets", lambda state: cast(CaseState, self.hydrate_ticket_contexts(cast(dict[str, Any], state))))
        graph.add_node(
            "intake_ticket_followup_decision",
            lambda state: cast(CaseState, dict(cast(dict[str, Any], state))),
        )
        graph.add_node(
            "intake_request_customer_input",
            lambda state: cast(CaseState, self.request_customer_input(cast(dict[str, Any], state))),
        )
        graph.add_node("intake_finalize", lambda state: cast(CaseState, self.finalize_state(cast(dict[str, Any], state))))
        graph.add_edge(START, "intake_prepare")
        graph.add_edge("intake_prepare", "intake_classify")
        graph.add_edge("intake_classify", "intake_mcp_tickets")
        graph.add_edge("intake_mcp_tickets", "intake_ticket_followup_decision")
        graph.add_conditional_edges(
            "intake_ticket_followup_decision",
            lambda state: self.route_after_ticket_followup_decision(cast(dict[str, Any], state)),
            {
                "request_customer_input": "intake_request_customer_input",
                "finalize": "intake_finalize",
            },
        )
        graph.add_edge("intake_request_customer_input", END)
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
    ticket_mcp_client = McpToolClient.from_config(config) if config.tools.mcp_manifest_path is not None else None
    agent = SampleIntakeAgent.from_ticket_mcp_client(config=config, ticket_mcp_client=ticket_mcp_client)
    result = agent.execute(raw_issue=args.issue)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())