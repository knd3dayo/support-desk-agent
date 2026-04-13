from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from support_ope_agents.agents.roles import COMPLIANCE_REVIEWER_AGENT, DRAFT_WRITER_AGENT, SUPERVISOR_AGENT
from support_ope_agents.config.models import AgentCatalogSettings


class SampleConfigTests(unittest.TestCase):
    def test_ai_platform_poc_uses_default_constraint_mode_by_default(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "samples" / "ai-platform-poc" / "config.yml"
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        settings = AgentCatalogSettings.model_validate(raw["support_ope_agents"]["agents"])

        self.assertEqual(settings.default_constraint_mode, "default")
        self.assertEqual(settings.resolve_constraint_mode(DRAFT_WRITER_AGENT), "default")
        self.assertEqual(settings.resolve_constraint_mode(COMPLIANCE_REVIEWER_AGENT), "default")
        self.assertEqual(settings.resolve_constraint_mode(SUPERVISOR_AGENT), "default")


if __name__ == "__main__":
    unittest.main()