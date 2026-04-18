from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from support_ope_agents.agents.roles import INVESTIGATE_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config import load_config
from support_ope_agents.config.models import AgentCatalogSettings


class SampleConfigTests(unittest.TestCase):
    def test_support_ope_agents_sample_uses_sample_runtime_mode(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "support-ope-agents" / "config-sample.yml"
        loaded = load_config(config_path)

        self.assertEqual(loaded.runtime.mode, "sample")

    def test_support_ope_agents_sample_uses_default_constraint_mode_by_default(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "support-ope-agents" / "config-sample.yml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        settings = AgentCatalogSettings.model_validate(raw["support_ope_agents"]["agents"])

        self.assertEqual(settings.default_constraint_mode, "default")
        self.assertEqual(settings.resolve_constraint_mode(INVESTIGATE_AGENT), "default")
        self.assertEqual(settings.resolve_constraint_mode(SUPERVISOR_AGENT), "default")

    def test_support_ope_agents_sample_configures_github_ticket_servers(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "support-ope-agents" / "config-sample.yml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        ticket_servers = raw["support_ope_agents"]["agents"]["IntakeAgent"]["ticket_servers"]
        external_ticket = ticket_servers["external"]
        internal_ticket = ticket_servers["internal"]

        self.assertEqual(external_ticket["server"], "github")
        self.assertEqual(internal_ticket["server"], "github")
        self.assertIn("repo", external_ticket["arguments"])
        self.assertIn("repo", internal_ticket["arguments"])
        self.assertEqual(external_ticket["candidate_matching"]["candidate_id_fields"], ["number", "issue_number", "id", "key"])
        self.assertEqual(internal_ticket["candidate_matching"]["min_combined_similarity"], 0.35)

    def test_load_config_allows_env_override_for_llm_model_and_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "support_ope_agents:",
                        "  llm:",
                        "    provider: openai",
                        "    model: poc-chat-model",
                        "    api_key: os.environ/LLM_API_KEY",
                        "    base_url: http://localhost:4000",
                        "  config_paths: {}",
                        "  data_paths: {}",
                        "  interfaces: {}",
                        "  agents: {}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "LLM_API_KEY": "sk-test-value",
                    "SUPPORT_OPE_LLM_MODEL": "gpt-4.1",
                    "SUPPORT_OPE_LLM_BASE_URL": "",
                },
                clear=False,
            ):
                loaded = load_config(config_path)

        self.assertEqual(loaded.llm.model, "gpt-4.1")
        self.assertIsNone(loaded.llm.base_url)


if __name__ == "__main__":
    unittest.main()