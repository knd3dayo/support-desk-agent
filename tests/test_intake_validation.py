from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.agents.production.intake_agent import IntakeAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.mcp_xml_toolset import XmlMcpToolsetProvider


class _FakeResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.raise_not_found_once = False

    def list_tools(self, server_name: str):
        class _Tool:
            def __init__(self, name: str, description: str, input_schema: dict[str, object]):
                self.name = name
                self.description = description
                self.input_schema = input_schema

        return (
            _Tool("get_issue", "Get a GitHub issue", {"type": "object", "properties": {"issue_number": {"type": "integer"}}}),
            _Tool("search_issues", "Search GitHub issues", {"type": "object", "properties": {"q": {"type": "string"}}}),
            _Tool("get_issue_attachments", "Get attachment metadata", {"type": "object", "properties": {"issue_number": {"type": "integer"}}}),
        )

    def list_tool_names(self, server_name: str) -> set[str]:
        return {tool.name for tool in self.list_tools(server_name)}

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, object]) -> str:
        self.calls.append((server_name, tool_name, arguments))
        if self.raise_not_found_once and tool_name == "get_issue":
            self.raise_not_found_once = False
            raise ValueError("Issue not found: 404")
        if tool_name == "search_issues":
            return '{"items":[{"number":121,"title":"Login failure incident","state":"open"},{"number":123,"title":"Login 500 on production","state":"open"}]}'
        if tool_name == "get_issue_attachments":
            return '{"attachments":[{"filename":"error.png","content":"binary-ish"}]}'
        return '{"title":"Issue 123","state":"open","body":"Customer impact details"}'


class _FakeStructuredModel:
    def invoke(self, _messages):
        return {
            "category": "incident_investigation",
            "urgency": "high",
            "investigation_focus": "障害影響を切り分ける",
            "reason": "mocked classification",
        }


class _FakeChatModel:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses

    def with_structured_output(self, _schema):
        return _FakeStructuredModel()

    def invoke(self, _messages):
        if not self._responses:
            raise AssertionError("unexpected extra invoke")
        return AIMessage(content=self._responses.pop(0))


class IntakeAgentValidationApiTests(unittest.TestCase):
    def test_normalize_incident_urgency_keeps_evidence_bearing_incident_at_least_medium(self) -> None:
        urgency = IntakeAgent._normalize_incident_urgency(
            "添付したファイルはvdp.logです。エラー調査をお願いします",
            "incident_investigation",
            "low",
        )

        self.assertEqual(urgency, "medium")

    def test_normalize_incident_urgency_raises_urgent_incident_to_high(self) -> None:
        urgency = IntakeAgent._normalize_incident_urgency(
            "本番障害です。至急確認してください",
            "incident_investigation",
            "medium",
        )

        self.assertEqual(urgency, "high")

    def test_instruction_only_and_bypass_skip_incident_urgency_normalization(self) -> None:
        for constraint_mode in ("instruction_only", "bypass"):
            config = AppConfig.model_validate(
                {
                    "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                    "config_paths": {},
                    "data_paths": {},
                    "interfaces": {},
                    "agents": {"IntakeAgent": {"constraint_mode": constraint_mode}},
                }
            )
            agent = IntakeAgent(
                config=config,
                pii_mask_tool=lambda *_args, **_kwargs: "",
                external_ticket_tool=lambda *_args, **_kwargs: "",
                internal_ticket_tool=lambda *_args, **_kwargs: "",
                classify_ticket_tool=lambda *_args, **_kwargs: "",
                write_shared_memory_tool=lambda *_args, **_kwargs: "",
            )

            urgency = agent._resolve_classification_urgency(
                "添付したファイルはvdp.logです。エラー調査をお願いします",
                "incident_investigation",
                "low",
            )

            self.assertEqual(urgency, "low")

    def test_global_bypass_is_used_when_intake_constraint_mode_is_omitted(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {"default_constraint_mode": "bypass"},
            }
        )
        agent = IntakeAgent(
            config=config,
            pii_mask_tool=lambda *_args, **_kwargs: "",
            external_ticket_tool=lambda *_args, **_kwargs: "",
            internal_ticket_tool=lambda *_args, **_kwargs: "",
            classify_ticket_tool=lambda *_args, **_kwargs: "",
            write_shared_memory_tool=lambda *_args, **_kwargs: "",
        )

        urgency = agent._resolve_classification_urgency(
            "添付したファイルはvdp.logです。エラー調査をお願いします",
            "incident_investigation",
            "low",
        )

        self.assertEqual(urgency, "low")

    def test_parse_classification_accepts_fenced_json(self) -> None:
        result = IntakeAgent._parse_classification(
            "```json\n"
            '{"category":"incident_investigation","urgency":"high","investigation_focus":"Denodo vdp.log error analysis","reason":"mocked"}'
            "\n```"
        )

        self.assertEqual(result["category"], "incident_investigation")
        self.assertEqual(result["urgency"], "high")
        self.assertEqual(result["investigation_focus"], "Denodo vdp.log error analysis")

    def test_validate_intake_requires_incident_timeframe_for_incident_cases(self) -> None:
        result = IntakeAgent.validate_intake(
            {
                "intake_category": "incident_investigation",
                "intake_urgency": "high",
            },
            {"context": "", "progress": "", "summary": ""},
        )

        self.assertEqual(result.category, "incident_investigation")
        self.assertEqual(result.urgency, "high")
        self.assertEqual(result.missing_fields, ["intake_incident_timeframe"])
        self.assertEqual(result.rework_reason, "障害発生時間帯が未確認")

    def test_validate_intake_skips_incident_timeframe_when_evidence_files_exist(self) -> None:
        result = IntakeAgent.validate_intake(
            {
                "intake_category": "incident_investigation",
                "intake_urgency": "high",
                "intake_evidence_files": [".evidence/vdp.log"],
            },
            {"context": "", "progress": "", "summary": ""},
        )

        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.rework_reason, "")

    def test_quality_gate_collects_workspace_evidence_files(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        agent = IntakeAgent(
            config=config,
            pii_mask_tool=lambda *_args, **_kwargs: "",
            external_ticket_tool=lambda *_args, **_kwargs: "",
            internal_ticket_tool=lambda *_args, **_kwargs: "",
            classify_ticket_tool=lambda *_args, **_kwargs: "",
            write_shared_memory_tool=lambda *_args, **_kwargs: "",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_path = Path(tmpdir) / ".evidence" / "vdp.log"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text("sample log\n", encoding="utf-8")

            result = agent.quality_gate(
                {
                    "workspace_path": tmpdir,
                    "intake_category": "incident_investigation",
                    "intake_urgency": "high",
                }
            )

        self.assertEqual(result.get("intake_missing_fields"), [])
        self.assertEqual(result.get("intake_evidence_files"), [".evidence/vdp.log"])

    def test_validate_intake_reads_category_and_urgency_from_memory_snapshot(self) -> None:
        result = IntakeAgent.validate_intake(
            {},
            {
                "context": "Category: specification_inquiry\nUrgency: low\nIncident timeframe: n/a",
                "progress": "",
                "summary": "",
            },
        )

        self.assertEqual(result.category, "specification_inquiry")
        self.assertEqual(result.urgency, "low")
        self.assertEqual(result.missing_fields, [])
        self.assertEqual(result.rework_reason, "")

    def test_resolve_effective_workflow_kind_prefers_specific_intake_category(self) -> None:
        resolved = IntakeAgent.resolve_effective_workflow_kind(
            {
                "workflow_kind": "ambiguous_case",
                "intake_category": "incident_investigation",
            },
            {"context": "", "progress": "", "summary": ""},
        )

        self.assertEqual(resolved, "incident_investigation")

    def test_hydrate_tickets_skips_when_mcp_ticket_tool_is_not_configured(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )
        agent = IntakeAgent(
            config=config,
            pii_mask_tool=lambda *_args, **_kwargs: "",
            external_ticket_tool=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("external_ticket tool is not configured. Configure tools.logical_tools.external_ticket in config.yml.")),
            internal_ticket_tool=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("internal_ticket tool is not configured. Configure tools.logical_tools.internal_ticket in config.yml.")),
            classify_ticket_tool=lambda *_args, **_kwargs: "",
            write_shared_memory_tool=lambda *_args, **_kwargs: "",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = agent.hydrate_tickets(
                {
                    "raw_issue": "内部外部チケットを確認してください",
                    "workspace_path": tmpdir,
                    "external_ticket_id": "EXT-123",
                    "internal_ticket_id": "INT-456",
                    "external_ticket_lookup_enabled": True,
                    "internal_ticket_lookup_enabled": True,
                }
            )

        self.assertFalse(bool(result.get("external_ticket_lookup_enabled")))
        self.assertFalse(bool(result.get("internal_ticket_lookup_enabled")))
        self.assertEqual(result.get("intake_ticket_context_summary"), {})
        self.assertEqual(result.get("intake_ticket_artifacts"), {})

    def test_hydrate_tickets_uses_mcp_ticket_server_with_custom_decision_tag(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "tools": {
                    "ticket_sources": {
                        "external": {
                            "enabled": True,
                            "server": "github",
                            "decision_tag": "ticket_decision",
                            "arguments": {"owner": "acme", "repo": "external-support"},
                        }
                    }
                },
                "agents": {},
            }
        )
        provider = XmlMcpToolsetProvider(backend=_FakeResolver())  # type: ignore[arg-type]
        agent = IntakeAgent(
            config=config,
            pii_mask_tool=lambda *_args, **_kwargs: "",
            external_ticket_tool=lambda *_args, **_kwargs: "",
            internal_ticket_tool=lambda *_args, **_kwargs: "",
            classify_ticket_tool=lambda *_args, **_kwargs: "",
            write_shared_memory_tool=lambda *_args, **_kwargs: "",
            ticket_mcp_provider=provider,
        )
        model = _FakeChatModel(
            [
                "<ticket_decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"123\"}</get_arguments><list_tool>search_issues</list_tool><list_arguments>{\"q\": \"login 500\"}</list_arguments><get_attachment_tool>get_issue_attachments</get_attachment_tool><get_attachment_arguments>{\"issue_number\": \"123\"}</get_attachment_arguments></ticket_decision>"
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("support_ope_agents.agents.production.intake_agent.build_chat_openai_model", return_value=model):
                result = agent.hydrate_tickets(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "123",
                        "external_ticket_lookup_enabled": True,
                    }
                )

        summary = result.get("intake_ticket_context_summary") or {}
        self.assertIn("external_ticket", summary)
        self.assertIn("Issue 123", str(summary["external_ticket"]))

    def test_hydrate_tickets_not_found_builds_ticket_followup_question(self) -> None:
        resolver = _FakeResolver()
        resolver.raise_not_found_once = True
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "tools": {
                    "ticket_sources": {
                        "external": {
                            "enabled": True,
                            "server": "github",
                            "arguments": {"owner": "acme", "repo": "external-support"},
                        }
                    }
                },
                "agents": {},
            }
        )
        provider = XmlMcpToolsetProvider(backend=resolver)  # type: ignore[arg-type]
        agent = IntakeAgent(
            config=config,
            pii_mask_tool=lambda *_args, **_kwargs: "",
            external_ticket_tool=lambda *_args, **_kwargs: "",
            internal_ticket_tool=lambda *_args, **_kwargs: "",
            classify_ticket_tool=lambda *_args, **_kwargs: "",
            write_shared_memory_tool=lambda *_args, **_kwargs: "",
            ticket_mcp_provider=provider,
        )
        model = _FakeChatModel(
            [
                "<decision><get_tool>get_issue</get_tool><get_arguments>{\"issue_number\": \"999\"}</get_arguments><list_tool>search_issues</list_tool><list_arguments>{\"q\": \"login 500\"}</list_arguments><get_attachment_tool>skip</get_attachment_tool></decision>"
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("support_ope_agents.agents.production.intake_agent.build_chat_openai_model", return_value=model):
                result = agent.hydrate_tickets(
                    {
                        "raw_issue": "ログイン時の 500 エラーを調査してください",
                        "workspace_path": tmpdir,
                        "external_ticket_id": "999",
                        "external_ticket_lookup_enabled": True,
                    }
                )

        questions = result.get("intake_followup_questions") or {}
        self.assertIn("external_ticket_confirmation", questions)


if __name__ == "__main__":
    unittest.main()