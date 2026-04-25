from __future__ import annotations

import asyncio
from datetime import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_chat_util.ai_chat_util_base.ai_chat_util_models import ChatResponse

from support_ope_agents.agents.production.investigate_agent import InvestigateAgent, InvestigateAgentTools
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.builtin_tools import build_builtin_tools
from support_ope_agents.tools.infer_log_pattern import build_default_infer_log_pattern_tool
from support_ope_agents.tools.registry import ToolRegistry
from support_ope_agents.util.ai_chat_util_bridge import build_ai_chat_util_config
from support_ope_agents.util.log_time_range import derive_log_extract_range_from_timeframe


class _FakeStructuredModel:
    def invoke(self, _messages):
        return {
            "header_pattern": r"^\d+\s+\[[^\]]+\]\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\d{4}-\d{2}-\d{2}T",
            "timestamp_start": 16,
            "timestamp_end": 39,
            "timestamp_format": "%Y-%m-%dT%H:%M:%S.%f",
            "confidence": 0.93,
            "reason": "先頭行で時刻が固定位置にあります。",
        }


class _FakeModel:
    def with_structured_output(self, _schema):
        return _FakeStructuredModel()


class _FakeTimeRangeStructuredModel:
    def invoke(self, _messages):
        return {
            "range_start": "2026-04-20T18:00:00",
            "range_end": "2026-04-20T21:00:00",
            "reason": "昨日の夕方を 18:00-21:00 と解釈しました。",
        }


class _FakeTimeRangeModel:
    def with_structured_output(self, _schema):
        return _FakeTimeRangeStructuredModel()


class LogRangeToolTests(unittest.TestCase):
    def _build_config(self) -> AppConfig:
        return AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

    def test_extract_log_time_range_saves_matching_records(self) -> None:
        config = self._build_config()
        tools = build_builtin_tools(config)
        handler = tools["extract_log_time_range"].handler

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            log_path = workspace_path / "vdp.log"
            log_path.write_text(
                "100 [main] INFO 2025-10-21T20:32:35.845 start\n"
                "startup detail\n"
                "200 [main] ERROR 2025-10-21T20:55:12.313 failure\n"
                "com.example.CacheException: boom\n"
                "300 [main] INFO 2025-10-21T21:00:00.000 end\n",
                encoding="utf-8",
            )

            raw = asyncio.run(
                handler(
                    str(log_path),
                    str(workspace_path),
                    r"^\d+\s+\[[^\]]+\]\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\d{4}-\d{2}-\d{2}T",
                    16,
                    39,
                    "2025-10-21T20:50:00.000",
                    "2025-10-21T20:56:00.000",
                    "%Y-%m-%dT%H:%M:%S.%f",
                )
            )
            payload = json.loads(raw)

            self.assertEqual(payload["status"], "matched")
            self.assertEqual(payload["matched_record_count"], 1)
            output_path = Path(payload["output_path"])
            self.assertTrue(output_path.exists())
            rendered = output_path.read_text(encoding="utf-8")
            self.assertIn("2025-10-21T20:55:12.313 failure", rendered)
            self.assertIn("com.example.CacheException: boom", rendered)

    def test_extract_log_time_range_accepts_iso_range_without_matching_time_format(self) -> None:
        config = self._build_config()
        tools = build_builtin_tools(config)
        handler = tools["extract_log_time_range"].handler

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            log_path = workspace_path / "vdp.log"
            log_path.write_text(
                "100 [main] INFO 2025-10-21T20:32:35.845 start\n"
                "200 [main] ERROR 2025-10-21T20:55:12.313 failure\n",
                encoding="utf-8",
            )

            raw = asyncio.run(
                handler(
                    str(log_path),
                    str(workspace_path),
                    r"^\d+\s+\[[^\]]+\]\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\d{4}-\d{2}-\d{2}T",
                    16,
                    39,
                    "2025-10-21T20:50:00",
                    "2025-10-21T20:56:00",
                    "%Y-%m-%dT%H:%M:%S.%f",
                )
            )
            payload = json.loads(raw)

            self.assertEqual(payload["matched_record_count"], 1)

    def test_infer_log_header_pattern_returns_structured_payload(self) -> None:
        config = self._build_config()
        tool = build_default_infer_log_pattern_tool(config)

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "vdp.log"
            log_path.write_text(
                "100 [main] INFO 2025-10-21T20:32:35.845 start\n",
                encoding="utf-8",
            )

            with patch("support_ope_agents.tools.infer_log_pattern.build_chat_openai_model", return_value=_FakeModel()):
                payload = json.loads(tool(file_path=str(log_path), sample_line_limit=20))

        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["timestamp_start"], 16)
        self.assertEqual(payload["timestamp_end"], 39)
        self.assertEqual(payload["timestamp_format"], "%Y-%m-%dT%H:%M:%S.%f")
        self.assertTrue(payload["header_pattern"])

    def test_builtin_tools_expose_input_schema_from_annotations(self) -> None:
        config = self._build_config()
        tools = build_builtin_tools(config)

        infer_schema = tools["infer_log_header_pattern"].input_schema
        self.assertEqual(infer_schema["type"], "object")
        self.assertIn("file_path", infer_schema["properties"])
        self.assertEqual(infer_schema["properties"]["file_path"]["type"], "string")
        self.assertEqual(infer_schema["properties"]["file_path"]["description"], "解析対象のログファイルパス")
        self.assertIn("file_path", infer_schema["required"])

        extract_schema = tools["extract_log_time_range"].input_schema
        self.assertEqual(extract_schema["properties"]["timestamp_start"]["type"], "integer")
        self.assertEqual(extract_schema["properties"]["output_subdir"]["default"], "log_extracts")

    def test_registry_exposes_new_investigate_tools(self) -> None:
        config = self._build_config()
        registry = ToolRegistry(config)

        tools = {tool.name: tool for tool in registry.get_tools("InvestigateAgent")}

        self.assertIn("infer_log_header_pattern", tools)
        self.assertIn("extract_log_time_range", tools)
        self.assertIn("file_path", tools["infer_log_header_pattern"].input_schema["properties"])

    def test_ai_chat_util_bridge_uses_support_config_as_primary_source(self) -> None:
        config = self._build_config()

        bridged = build_ai_chat_util_config(config)

        self.assertEqual(bridged.llm.provider, config.llm.provider)
        self.assertEqual(bridged.llm.completion_model, config.llm.model)
        self.assertEqual(bridged.llm.api_key, config.llm.api_key)
        self.assertEqual(bridged.office2pdf.libreoffice_path, config.tools.libreoffice_command)

    def test_analyze_pdf_files_delegates_to_ai_chat_util(self) -> None:
        config = self._build_config()
        tools = build_builtin_tools(config)
        handler = tools["analyze_pdf_files"].handler

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            with patch(
                "support_ope_agents.tools.builtin_tools.analyze_pdf_files_with_ai_chat_util",
                return_value="delegated via ai-chat-util",
            ) as delegated:
                result = asyncio.run(handler([str(pdf_path)], "check this", "auto"))

        self.assertEqual(result, "delegated via ai-chat-util")
        delegated.assert_called_once()

    def test_chat_response_text_normalization_uses_output_property(self) -> None:
        response = ChatResponse.model_validate({"output": " normalized text "})

        self.assertEqual(response.output, " normalized text ")

    def test_investigate_agent_appends_extraction_summary(self) -> None:
        config = self._build_config()
        agent = InvestigateAgent(
            config=config,
            tools=InvestigateAgentTools(
                detect_log_format_tool=lambda *_args, **_kwargs: json.dumps(
                    {
                        "detected_format": "unknown",
                        "search_results": {"severity": [], "java_exception": []},
                    },
                    ensure_ascii=False,
                ),
                infer_log_header_pattern_tool=lambda *_args, **_kwargs: json.dumps(
                    {
                        "header_pattern": r"^\d+\s+\[[^\]]+\]\s+(?:TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+\d{4}-\d{2}-\d{2}T",
                        "timestamp_start": 16,
                        "timestamp_end": 39,
                        "timestamp_format": "%Y-%m-%dT%H:%M:%S.%f",
                    },
                    ensure_ascii=False,
                ),
                extract_log_time_range_tool=lambda *_args, **_kwargs: json.dumps(
                    {
                        "output_path": "/tmp/extracted.log",
                        "matched_record_count": 2,
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir)
            evidence_dir = workspace_path / ".evidence"
            evidence_dir.mkdir()
            (evidence_dir / "vdp.log").write_text("sample\n", encoding="utf-8")

            result = agent.execute(
                {
                    "workspace_path": str(workspace_path),
                    "raw_issue": "vdp.log のエラーを見て",
                    "log_extract_range_start": "2025-10-21T20:50:00.000",
                    "log_extract_range_end": "2025-10-21T20:56:00.000",
                }
            )

        summary = str(result.get("log_analysis_summary") or "")
        self.assertIn("/tmp/extracted.log", summary)
        self.assertIn("指定時間帯", summary)

    def test_derive_log_extract_range_uses_llm_for_ambiguous_timeframe(self) -> None:
        config = self._build_config()
        with patch("support_ope_agents.util.log_time_range.build_chat_openai_model", return_value=_FakeTimeRangeModel()):
            derived = derive_log_extract_range_from_timeframe(
                "昨日の夕方に発生しました。",
                config=config,
                reference_datetime=datetime(2026, 4, 21, 9, 0, 0),
            )

        self.assertEqual(derived, ("2026-04-20T18:00:00", "2026-04-20T21:00:00"))


if __name__ == "__main__":
    unittest.main()