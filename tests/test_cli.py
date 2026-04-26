from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from support_ope_agents.cli import _cmd_evaluate_investigate, _cmd_run_sample_supervisor, build_parser


class _FakeEvaluation:
    def model_dump(self) -> dict[str, object]:
        return {
            "criterion_evaluations": [],
            "agent_evaluations": [{"agent_name": "InvestigateAgent", "score": 80, "comment": "ok"}],
            "overall_summary": "summary",
            "improvement_points": [],
            "overall_score": 80,
        }


class CliTests(unittest.TestCase):
    def test_build_parser_accepts_evaluate_investigate(self) -> None:
        parser = build_parser()

        args = parser.parse_args([
            "evaluate-investigate",
            "ログを調べて",
            "--config",
            "config.yml",
            "--workspace-path",
            "/tmp/case",
            "--checklist-template",
            "basic",
            "--checklist",
            "原因候補があること",
            "--output",
            "/tmp/out.json",
        ])

        self.assertEqual(args.command, "evaluate-investigate")
        self.assertEqual(args.prompt, "ログを調べて")
        self.assertEqual(args.workspace_path, "/tmp/case")
        self.assertEqual(args.checklist_template, "basic")
        self.assertEqual(args.checklist, ["原因候補があること"])
        self.assertEqual(args.output, "/tmp/out.json")

    def test_build_parser_accepts_run_sample_supervisor(self) -> None:
        parser = build_parser()

        args = parser.parse_args([
            "run-sample-supervisor",
            "vdp.log の内容から障害原因を要約してください",
            "--config",
            "config.yml",
            "--workspace-path",
            "/tmp/case",
            "--case-id",
            "CASE-001",
            "--output",
            "/tmp/supervisor.json",
        ])

        self.assertEqual(args.command, "run-sample-supervisor")
        self.assertEqual(args.prompt, "vdp.log の内容から障害原因を要約してください")
        self.assertEqual(args.workspace_path, "/tmp/case")
        self.assertEqual(args.case_id, "CASE-001")
        self.assertEqual(args.output, "/tmp/supervisor.json")

    def test_cmd_evaluate_investigate_prints_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / ".support-ope-case-id").write_text("CASE-TEST\n", encoding="utf-8")
            evidence_dir = workspace / ".evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "vdp.log").write_text("sample\n", encoding="utf-8")

            args = SimpleNamespace(
                config="config.yml",
                workspace_path=str(workspace),
                case_id=None,
                prompt="ログを調べて",
                checklist_template="basic",
                checklist=["根拠があること"],
                output=str(workspace / "evaluation.json"),
            )
            stdout = io.StringIO()

            with patch("support_ope_agents.cli.load_config") as load_config_mock:
                with patch("support_ope_agents.cli.SampleInvestigateAgent") as investigate_mock:
                    with patch("support_ope_agents.cli.InstructionLoader") as instruction_loader_mock:
                        with patch("support_ope_agents.cli.ObjectiveEvaluator") as evaluator_mock:
                            load_config_mock.return_value = SimpleNamespace(data_paths=SimpleNamespace(evidence_subdir=".evidence"))
                            load_config_mock.return_value = SimpleNamespace(
                                data_paths=SimpleNamespace(
                                    shared_memory_subdir=".memory",
                                    artifacts_subdir=".artifacts",
                                    evidence_subdir=".evidence",
                                    report_subdir=".report",
                                    trace_subdir=".traces",
                                )
                            )
                            investigate_mock.return_value.execute.return_value = {"output": "調査結果"}
                            investigate_mock.return_value.read_investigate_working_memory.return_value = "working"
                            instruction_loader_mock.return_value.load.return_value = "base instruction"
                            evaluator_mock.return_value.evaluate.return_value = _FakeEvaluation()

                            with redirect_stdout(stdout):
                                exit_code = _cmd_evaluate_investigate(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["case_id"], "CASE-TEST")
            self.assertEqual(payload["investigation_result"], "調査結果")
            self.assertEqual(payload["evaluation"]["overall_score"], 80)
            self.assertIn("結論または現時点の判断", payload["checklist"][0])
            self.assertEqual(payload["output_path"], str((workspace / "evaluation.json").resolve()))
            self.assertTrue((workspace / "evaluation.json").exists())

    def test_cmd_run_sample_supervisor_prints_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / ".support-ope-case-id").write_text("CASE-TEST-SUPERVISOR\n", encoding="utf-8")

            args = SimpleNamespace(
                config="config.yml",
                workspace_path=str(workspace),
                case_id=None,
                prompt="vdp.log の内容から障害原因を要約してください",
                output=str(workspace / "supervisor.json"),
            )
            stdout = io.StringIO()

            final_state = {
                "case_id": "CASE-TEST-SUPERVISOR",
                "status": "DRAFT_READY",
                "draft_response": "回答ドラフト",
                "next_action": "ApprovalAgent へドラフトを回付する",
            }

            with patch("support_ope_agents.cli.load_config") as load_config_mock:
                with patch("support_ope_agents.cli.SampleInvestigateAgent") as investigate_mock:
                    with patch("support_ope_agents.cli.SampleSupervisorAgent") as supervisor_mock:
                        load_config_mock.return_value = SimpleNamespace(
                            data_paths=SimpleNamespace(
                                shared_memory_subdir=".memory",
                                artifacts_subdir=".artifacts",
                                evidence_subdir=".evidence",
                                report_subdir=".report",
                                trace_subdir=".traces",
                            )
                        )
                        investigate_mock.return_value = object()
                        supervisor_instance = supervisor_mock.return_value
                        supervisor_instance.execute_investigation.return_value = {
                            "case_id": "CASE-TEST-SUPERVISOR",
                            "escalation_required": False,
                            "investigation_summary": "要約",
                        }
                        supervisor_instance.route_after_investigation.return_value = "draft_review"
                        supervisor_instance.execute_draft_review.return_value = final_state

                        with redirect_stdout(stdout):
                            exit_code = _cmd_run_sample_supervisor(args)

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["case_id"], "CASE-TEST-SUPERVISOR")
            self.assertEqual(payload["route"], "draft_review")
            self.assertEqual(payload["state"]["draft_response"], "回答ドラフト")
            self.assertEqual(payload["output_path"], str((workspace / "supervisor.json").resolve()))
            self.assertTrue((workspace / "supervisor.json").exists())


if __name__ == "__main__":
    unittest.main()