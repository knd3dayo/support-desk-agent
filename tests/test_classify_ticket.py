from __future__ import annotations

import asyncio
import json
import unittest

from support_ope_agents.config.models import AppConfig
from support_ope_agents.tools.default_classify_ticket import build_default_classify_ticket_tool


class ClassifyTicketTests(unittest.TestCase):
    def test_fallback_treats_feature_list_request_as_specification_inquiry(self) -> None:
        config = AppConfig.model_validate(
            {
                "llm": {"provider": "mock", "model": "gpt-4.1", "api_key": "dummy"},
                "config_paths": {},
                "data_paths": {},
                "interfaces": {},
                "agents": {},
            }
        )

        result = json.loads(asyncio.run(build_default_classify_ticket_tool(config)("ai-chat-utilの機能一覧を出して")))

        self.assertEqual(result["category"], "specification_inquiry")
        self.assertEqual(result["urgency"], "medium")


if __name__ == "__main__":
    unittest.main()