from __future__ import annotations

import asyncio
from datetime import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.agents.production.investigate_agent import InvestigateAgent
from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.builtin_tools import build_builtin_tools
from support_ope_agents.tools.default_infer_log_pattern import build_default_infer_log_pattern_tool
from support_ope_agents.tools.registry import ToolRegistry
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

            with patch("support_ope_agents.tools.default_infer_log_pattern.build_chat_openai_model", return_value=_FakeModel()):
                payload = json.loads(tool(file_path=str(log_path), sample_line_limit=20))

        self.assertEqual(payload["status"], "matched")
        self.assertEqual(payload["timestamp_start"], 16)
        self.assertEqual(payload["timestamp_end"], 39)
        self.assertEqual(payload["timestamp_format"], "%Y-%m-%dT%H:%M:%S.%f")
        self.assertTrue(payload["header_pattern"])

    def test_registry_exposes_new_investigate_tools(self) -> None:
        config = self._build_config()
        registry = ToolRegistry(config)

        tools = {tool.name: tool for tool in registry.get_tools("InvestigateAgent")}

        self.assertIn("infer_log_header_pattern", tools)
        self.assertIn("extract_log_time_range", tools)

    def test_investigate_agent_appends_extraction_summary(self) -> None:
        config = self._build_config()
        agent = InvestigateAgent(
            config=config,
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