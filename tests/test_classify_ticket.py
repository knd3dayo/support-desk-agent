from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_classify_ticket import build_default_classify_ticket_tool


class _FakeModel:
    async def ainvoke(self, _messages):
        return AIMessage(
            content=json.dumps(
                {
                    "category": "specification_inquiry",
                    "urgency": "medium",
                    "investigation_focus": "期待動作と現行仕様の差分を確認する",
                    "reason": "mocked llm classification",
                },
                ensure_ascii=False,
            )
        )


class ClassifyTicketTests(unittest.TestCase):
    def test_classify_ticket_uses_llm_response(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-test-value"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        with patch("support_ope_agents.tools.default_classify_ticket._get_chat_model", return_value=_FakeModel()):
            result = json.loads(asyncio.run(build_default_classify_ticket_tool(config)("ai-chat-utilの機能一覧を出して")))

        self.assertEqual(result["category"], "specification_inquiry")
        self.assertEqual(result["urgency"], "medium")


if __name__ == "__main__":
    unittest.main()