from __future__ import annotations

from pathlib import Path

from fastapi import Depends
from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import Header
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from support_ope_agents.runtime import RuntimeService, build_runtime_context

from .schemas import (
    ActionRequest,
    CaseSummary,
    ChatHistoryResponse,
    CreateCaseRequest,
    DescribeAgentsRequest,
    InitCaseRequest,
    InitCaseResponse,
    PlanRequest,
    ResumeCustomerInputRequest,
    RuntimeEnvelope,
    WorkspaceBrowseResponse,
    WorkspaceFileResponse,
    WorkspaceUploadResponse,
)


def create_app(config_path: str = "config.yml") -> FastAPI:
    context = build_runtime_context(config_path)
    service = RuntimeService(context)
    app = FastAPI(title="support-ope-agents API", version="0.1.0")
    base_dir = Path(config_path).resolve().parent
    default_cases_root = base_dir / "work" / "cases"

    if context.config.interfaces.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=context.config.interfaces.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def resolve_workspace_path(case_id: str, workspace_path: str | None) -> str:
        return workspace_path or str(default_cases_root / case_id)

    def map_error(exc: Exception) -> HTTPException:
        if isinstance(exc, FileNotFoundError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, NotADirectoryError | IsADirectoryError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        return HTTPException(status_code=500, detail=str(exc))

    def require_auth(
        authorization: str | None = Header(default=None),
        x_support_ope_token: str | None = Header(default=None),
    ) -> None:
        interfaces = context.config.interfaces
        if not interfaces.auth_required:
            return

        expected = interfaces.auth_token or ""
        bearer_prefix = "Bearer "
        candidates = [x_support_ope_token]
        if authorization and authorization.startswith(bearer_prefix):
            candidates.append(authorization[len(bearer_prefix) :])
        if expected not in candidates:
            raise HTTPException(status_code=401, detail="authentication required")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/cases", response_model=list[CaseSummary])
    def list_cases(cases_root: str = Query(default=str(default_cases_root)), _: None = Depends(require_auth)) -> list[CaseSummary]:
        return [CaseSummary.model_validate(item) for item in service.list_cases(cases_root)]

    @app.post("/cases", response_model=InitCaseResponse)
    def create_case(
        request: CreateCaseRequest,
        cases_root: str = Query(default=str(default_cases_root)),
        _: None = Depends(require_auth),
    ) -> InitCaseResponse:
        try:
            payload = service.create_case(cases_root=cases_root, prompt=request.prompt, case_id=request.case_id)
        except Exception as exc:
            raise map_error(exc) from exc
        return InitCaseResponse.model_validate(payload)

    @app.get("/cases/{case_id}/history", response_model=ChatHistoryResponse)
    def get_case_history(case_id: str, workspace_path: str | None = None, _: None = Depends(require_auth)) -> ChatHistoryResponse:
        resolved_workspace = resolve_workspace_path(case_id, workspace_path)
        try:
            messages = service.get_chat_history(case_id=case_id, workspace_path=resolved_workspace)
        except Exception as exc:
            raise map_error(exc) from exc
        return ChatHistoryResponse(case_id=case_id, workspace_path=resolved_workspace, messages=messages)

    @app.get("/cases/{case_id}/workspace", response_model=WorkspaceBrowseResponse)
    def browse_workspace(
        case_id: str,
        workspace_path: str | None = None,
        path: str = Query(default="."),
        _: None = Depends(require_auth),
    ) -> WorkspaceBrowseResponse:
        resolved_workspace = resolve_workspace_path(case_id, workspace_path)
        try:
            payload = service.list_workspace_entries(case_id=case_id, workspace_path=resolved_workspace, relative_path=path)
        except Exception as exc:
            raise map_error(exc) from exc
        return WorkspaceBrowseResponse.model_validate(payload)

    @app.get("/cases/{case_id}/workspace/file", response_model=WorkspaceFileResponse)
    def get_workspace_file(
        case_id: str,
        workspace_path: str | None = None,
        path: str = Query(...),
        max_chars: int = Query(default=16000, ge=1, le=200000),
        _: None = Depends(require_auth),
    ) -> WorkspaceFileResponse:
        resolved_workspace = resolve_workspace_path(case_id, workspace_path)
        try:
            payload = service.get_workspace_file(
                case_id=case_id,
                workspace_path=resolved_workspace,
                relative_path=path,
                max_chars=max_chars,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return WorkspaceFileResponse.model_validate(payload)

    @app.get("/cases/{case_id}/workspace/raw")
    def get_workspace_raw_file(
        case_id: str,
        workspace_path: str | None = None,
        path: str = Query(...),
        _: None = Depends(require_auth),
    ) -> FileResponse:
        resolved_workspace = resolve_workspace_path(case_id, workspace_path)
        try:
            target = service.workspace_file_path(case_id=case_id, workspace_path=resolved_workspace, relative_path=path)
        except Exception as exc:
            raise map_error(exc) from exc
        return FileResponse(path=target)

    @app.post("/cases/{case_id}/workspace/upload", response_model=WorkspaceUploadResponse)
    async def upload_workspace_file(
        case_id: str,
        workspace_path: str | None = Form(default=None),
        relative_dir: str = Form(default="."),
        file: UploadFile = File(...),
        _: None = Depends(require_auth),
    ) -> WorkspaceUploadResponse:
        resolved_workspace = resolve_workspace_path(case_id, workspace_path)
        try:
            content = await file.read()
            payload = service.save_workspace_file(
                case_id=case_id,
                workspace_path=resolved_workspace,
                relative_dir=relative_dir,
                filename=file.filename or "upload.bin",
                content=content,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return WorkspaceUploadResponse.model_validate(payload)

    @app.get("/cases/{case_id}/workspace/download")
    def download_workspace(case_id: str, workspace_path: str | None = None, _: None = Depends(require_auth)) -> FileResponse:
        resolved_workspace = resolve_workspace_path(case_id, workspace_path)
        try:
            archive_path = service.create_workspace_archive(case_id=case_id, workspace_path=resolved_workspace)
        except Exception as exc:
            raise map_error(exc) from exc
        return FileResponse(path=archive_path, filename=archive_path.name, media_type="application/zip")

    @app.post("/init-case", response_model=InitCaseResponse)
    def init_case(request: InitCaseRequest, _: None = Depends(require_auth)) -> InitCaseResponse:
        case_id = service.resolve_case_id(prompt=request.prompt, workspace_path=request.workspace_path)
        case_path = service.initialize_case(case_id, workspace_path=request.workspace_path)
        return InitCaseResponse(case_id=case_id, case_path=str(case_path))

    @app.post("/describe-agents")
    def describe_agents(request: DescribeAgentsRequest, _: None = Depends(require_auth)) -> list[dict[str, object]]:
        case_id = service.resolve_case_id(prompt=request.prompt)
        return service.describe_agents(case_id)

    @app.post("/plan", response_model=RuntimeEnvelope)
    def plan(request: PlanRequest, _: None = Depends(require_auth)) -> RuntimeEnvelope:
        result = service.plan(
            prompt=request.prompt,
            workspace_path=request.workspace_path,
            external_ticket_id=request.external_ticket_id,
            internal_ticket_id=request.internal_ticket_id,
        )
        return RuntimeEnvelope.model_validate(result)

    @app.post("/action", response_model=RuntimeEnvelope)
    def action(request: ActionRequest, _: None = Depends(require_auth)) -> RuntimeEnvelope:
        result = service.action(
            prompt=request.prompt,
            workspace_path=request.workspace_path,
            trace_id=request.trace_id,
            execution_plan=request.execution_plan,
            external_ticket_id=request.external_ticket_id,
            internal_ticket_id=request.internal_ticket_id,
        )
        return RuntimeEnvelope.model_validate(result)

    @app.post("/resume-customer-input", response_model=RuntimeEnvelope)
    def resume_customer_input(request: ResumeCustomerInputRequest, _: None = Depends(require_auth)) -> RuntimeEnvelope:
        result = service.resume_customer_input(
            case_id=request.case_id,
            trace_id=request.trace_id,
            workspace_path=request.workspace_path,
            additional_input=request.additional_input,
            answer_key=request.answer_key,
            external_ticket_id=request.external_ticket_id,
            internal_ticket_id=request.internal_ticket_id,
        )
        return RuntimeEnvelope.model_validate(result)

    frontend_dist = base_dir / "frontend" / "dist"
    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def serve_spa_index() -> FileResponse:
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{spa_path:path}", include_in_schema=False)
        def serve_spa(spa_path: str) -> FileResponse:
            candidate = (frontend_dist / spa_path).resolve()
            if spa_path and candidate.is_file() and candidate.is_relative_to(frontend_dist):
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app