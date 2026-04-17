from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.agents.production.intake_agent import IntakeAgent
from support_ope_agents.config.models import AppConfig


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


if __name__ == "__main__":
    unittest.main()