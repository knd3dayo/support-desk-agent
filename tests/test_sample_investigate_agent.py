from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support_ope_agents.agents.sample.sample_investigate_agent import SampleInvestigateAgent
from support_ope_agents.agents.sample.sample_supervisor_agent import SampleSupervisorAgent
from support_ope_agents.config.models import AppConfig


class _FakeSubAgent:
    def invoke(self, _payload: object) -> dict[str, object]:
        return {"output": "ドキュメント補足: Denodo の一般的な構成説明です。"}


class _WorkspaceAwareInvestigateExecutor:
    def execute(self, *, query: str, workspace_path: str | None = None) -> dict[str, object]:
        del query
        return {"output": f"workspace={workspace_path or 'missing'}"}


class SampleInvestigateAgentTests(unittest.TestCase):
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

    def test_execute_prioritizes_workspace_log_evidence(self) -> None:
        agent = SampleInvestigateAgent(self._build_config())

        with tempfile.TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text(
                "2025-10-21T20:55:12 ERROR Error loading server cache data source.\n"
                "com.denodo.vdb.cache.VDBCacheException: Data source vdpcachedatasource not found\n",
                encoding="utf-8",
            )
            with patch.object(agent, "create_sub_agent", return_value=_FakeSubAgent()):
                result = agent.execute(query="このログのフォーマットを教えて", workspace_path=tmpdir)

        summary = str(result)
        self.assertIn("vdp.log", summary)
        self.assertIn("vdpcachedatasource not found", summary)
        self.assertIn("補足情報", summary)

    def test_supervisor_passes_workspace_path_to_sample_investigation(self) -> None:
        supervisor = SampleSupervisorAgent(investigate_executor=_WorkspaceAwareInvestigateExecutor())

        with tempfile.TemporaryDirectory() as tmpdir:
            result = supervisor.execute_investigation(
                {
                    "case_id": "CASE-TEST-SAMPLE-001",
                    "workspace_path": tmpdir,
                    "raw_issue": "このログのフォーマットを教えて",
                }
            )

        self.assertEqual(str(result.get("investigation_summary") or ""), f"workspace={tmpdir}")


if __name__ == "__main__":
    unittest.main()