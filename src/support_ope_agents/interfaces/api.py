from __future__ import annotations

from fastapi import FastAPI

from support_ope_agents.runtime import RuntimeService, build_runtime_context

from .schemas import ActionRequest, DescribeAgentsRequest, InitCaseRequest, InitCaseResponse, PlanRequest, RuntimeEnvelope


def create_app(config_path: str = "config.yml") -> FastAPI:
    service = RuntimeService(build_runtime_context(config_path))
    app = FastAPI(title="support-ope-agents API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/init-case", response_model=InitCaseResponse)
    def init_case(request: InitCaseRequest) -> InitCaseResponse:
        case_id = service.resolve_case_id(prompt=request.prompt, workspace_path=request.workspace_path)
        case_path = service.initialize_case(case_id, workspace_path=request.workspace_path)
        return InitCaseResponse(case_id=case_id, case_path=str(case_path))

    @app.post("/describe-agents")
    def describe_agents(request: DescribeAgentsRequest) -> list[dict[str, object]]:
        case_id = service.resolve_case_id(prompt=request.prompt)
        return service.describe_agents(case_id)

    @app.post("/plan", response_model=RuntimeEnvelope)
    def plan(request: PlanRequest) -> RuntimeEnvelope:
        result = service.plan(prompt=request.prompt, workspace_path=request.workspace_path)
        return RuntimeEnvelope.model_validate(result)

    @app.post("/action", response_model=RuntimeEnvelope)
    def action(request: ActionRequest) -> RuntimeEnvelope:
        result = service.action(
            prompt=request.prompt,
            workspace_path=request.workspace_path,
            trace_id=request.trace_id,
            execution_plan=request.execution_plan,
        )
        return RuntimeEnvelope.model_validate(result)

    return app