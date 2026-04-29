from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from support_desk_agent.agents.objective_evaluator import (
    ObjectiveEvaluator,
    ObjectiveEvaluatorStructuredResult,
    StructuredAgentEvaluation,
    StructuredCriterionEvaluation,
)
from support_desk_agent.interfaces.mcp import SupportOpeMcpAdapter


def _fake_objective_evaluation_result() -> ObjectiveEvaluatorStructuredResult:
    return ObjectiveEvaluatorStructuredResult(
        criterion_evaluations=[
            StructuredCriterionEvaluation(
                title="質問意図への回答妥当性",
                viewpoint="レポート生成時に回答妥当性を確認できているか",
                result="MCP 経路でも評価結果を返せています。",
                score=80,
            )
        ],
        agent_evaluations=[
            StructuredAgentEvaluation(agent_name="IntakeAgent", score=82, comment="入力整理は安定しています。")
        ],
        overall_summary="MCP 経由の report 生成に必要な structured evaluation は返却されています。",
        improvement_points=["shared summary を明示的に更新してください。"],
        overall_score=80,
    )


class _FakeClassifierModel:
    async def ainvoke(self, _messages):
        return AIMessage(content='{"category":"specification_inquiry","urgency":"medium","investigation_focus":"期待動作と現行仕様の差分を確認する","reason":"mocked llm classification"}')


class _FakeDraftModel:
    async def ainvoke(self, _messages):
        return AIMessage(content="お問い合わせありがとうございます。\n\n現時点の結論として、アーキテクチャ概要をご案内します。")


class _FakeComplianceModel:
    async def ainvoke(self, _messages):
        return AIMessage(content='{"summary":"mocked compliance review","issues":[]}')


class McpAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._objective_eval_patcher = patch.object(
            ObjectiveEvaluator,
            "_invoke_structured_evaluation",
            return_value=_fake_objective_evaluation_result(),
        )
        self._classify_model_patcher = patch(
            "support_desk_agent.tools.default_classify_ticket.build_chat_openai_model",
            return_value=_FakeClassifierModel(),
        )
        self._objective_eval_patcher.start()
        self._classify_model_patcher.start()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmpdir.name)
        self.workspace_path = self.repo_root / "work" / "cases" / "CASE-MCP-001"
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        (self.workspace_path / ".support-ope-case-id").write_text("CASE-MCP-001\n", encoding="utf-8")
        config_path = self.repo_root / "config.yml"
        config_path.write_text(
                        "\n".join([
                                "support_desk_agent:",
                                "  llm:",
                                "    provider: openai",
                                "    model: gpt-4.1",
                                "    api_key: sk-test-value",
                                "  config_paths: {}",
                                "  data_paths: {}",
                                "  interfaces: {}",
                                "  agents: {}",
                        ])
                        + "\n",
            encoding="utf-8",
        )
        self.adapter = SupportOpeMcpAdapter(str(config_path))

    def tearDown(self) -> None:
        self._classify_model_patcher.stop()
        self._objective_eval_patcher.stop()
        self._tmpdir.cleanup()

    def test_manifest_includes_generate_report_tool(self) -> None:
        manifest = self.adapter.manifest()

        tool_names = {tool["name"] for tool in manifest["tools"]}
        self.assertIn("generate_report", tool_names)

    def test_generate_report_tool_writes_report(self) -> None:
        plan = self.adapter.call_tool(
            "action",
            {
                "prompt": "生成AI基盤のアーキテクチャ概要を教えてください。",
                "workspace_path": str(self.workspace_path),
            },
        )

        result = self.adapter.call_tool(
            "generate_report",
            {
                "case_id": "CASE-MCP-001",
                "trace_id": str(plan["trace_id"]),
                "workspace_path": str(self.workspace_path),
                "checklist": ["KnowledgeRetrieverAgent が含まれているか"],
            },
        )

        report_path = Path(str(result["report_path"]))
        self.assertTrue(report_path.exists())
        self.assertEqual(report_path.parent.name, ".report")


if __name__ == "__main__":
    unittest.main()