from __future__ import annotations

from typing import Any

from support_ope_agents.runtime import RuntimeService, build_runtime_context

from .schemas import ActionRequest, PlanRequest


class SupportOpeMcpAdapter:
    def __init__(self, config_path: str = "config.yml"):
        self._service = RuntimeService(build_runtime_context(config_path))

    def manifest(self) -> dict[str, Any]:
        return {
            "server": "support-ope-agents",
            "transport": self._service.context.config.interfaces.mcp_transport,
            "tools": [
                {
                    "name": "plan",
                    "description": "Create an execution plan and return the trace_id used for continuation.",
                    "input_schema": PlanRequest.model_json_schema(),
                },
                {
                    "name": "action",
                    "description": "Continue execution using trace_id and an optional execution_plan.",
                    "input_schema": ActionRequest.model_json_schema(),
                },
            ],
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "plan":
            request = PlanRequest.model_validate(arguments)
            return self._service.plan(prompt=request.prompt, workspace_path=request.workspace_path)
        if name == "action":
            request = ActionRequest.model_validate(arguments)
            return self._service.action(
                prompt=request.prompt,
                workspace_path=request.workspace_path,
                trace_id=request.trace_id,
                execution_plan=request.execution_plan,
            )
        raise ValueError(f"Unsupported MCP tool: {name}")