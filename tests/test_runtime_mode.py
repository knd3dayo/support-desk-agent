from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support_ope_agents.config import load_config
from support_ope_agents.runtime import build_runtime_service


class RuntimeModeSelectionTests(unittest.TestCase):
    def _write_config(self, *, root: Path, mode: str | None) -> Path:
        lines = [
            "support_ope_agents:",
            "  llm:",
            "    provider: openai",
            "    model: gpt-4.1",
            "    api_key: sk-test-value",
            "  config_paths: {}",
            "  data_paths: {}",
        ]
        if mode is not None:
            lines.extend([
                "  runtime:",
                f"    mode: {mode}",
            ])
        lines.extend([
            "  interfaces: {}",
            "  agents: {}",
        ])
        config_path = root / "config.yml"
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return config_path

    def test_runtime_mode_defaults_to_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self._write_config(root=Path(tmpdir), mode=None)
            loaded = load_config(config_path)

        self.assertEqual(loaded.runtime.mode, "production")

    def test_runtime_package_selects_sample_runtime_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self._write_config(root=root, mode="sample")
            service = build_runtime_service(config_path)

            self.assertEqual(type(service).__module__, "support_ope_agents.runtime.sample.sample_service")
            self.assertEqual(
                service.print_workflow_nodes(),
                [
                    "__end__",
                    "__start__",
                    "intake_subgraph",
                    "receive_case",
                    "supervisor_subgraph",
                    "ticket_update_subgraph",
                    "wait_for_approval",
                ],
            )

    def test_runtime_package_selects_production_runtime_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self._write_config(root=root, mode=None)
            service = build_runtime_service(config_path)

            self.assertEqual(type(service).__module__, "support_ope_agents.runtime.production.production_service")
            self.assertEqual(
                service.print_workflow_nodes(),
                [
                    "__end__",
                    "__start__",
                    "intake_subgraph",
                    "receive_case",
                    "supervisor_subgraph",
                    "ticket_update_subgraph",
                    "wait_for_approval",
                    "wait_for_customer_input",
                ],
            )


if __name__ == "__main__":
    unittest.main()