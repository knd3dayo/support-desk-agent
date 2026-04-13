from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, cast

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
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
import uvicorn
import yaml

from support_ope_agents.config.models import AppConfig
from support_ope_agents.runtime import RuntimeService, build_runtime_context
from support_ope_agents.runtime.case_titles import derive_case_title
from support_ope_agents.runtime.conversation_messages import extract_serialized_messages_from_history

from .schemas import (
    ActionRequest,
    CaseSummary,
    ChatHistoryResponse,
    CreateCaseRequest,
    GenerateReportRequest,
    GenerateReportResponse,
    DescribeAgentsRequest,
    InitCaseRequest,
    InitCaseResponse,
    PlanRequest,
    ResumeCustomerInputRequest,
    RuntimeEnvelope,
    UiConfigResponse,
    WorkspaceBrowseResponse,
    WorkspaceFileResponse,
    WorkspaceUploadResponse,
)


DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000
STARTUP_LLM_PROBE_TIMEOUT_SECONDS = 15


def _build_startup_probe_model(config: AppConfig) -> ChatOpenAI:
    chat_openai = cast(Any, ChatOpenAI)
    return chat_openai(
        model=config.llm.model,
        api_key=cast(Any, config.llm.api_key),
        base_url=config.llm.base_url,
        temperature=0,
    )


def _stringify_probe_response(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts).strip()
    return str(content).strip()


async def _probe_llm_backend(config: AppConfig) -> None:
    model = _build_startup_probe_model(config)
    try:
        response = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content="Reply with a short readiness confirmation.")]),
            timeout=STARTUP_LLM_PROBE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise RuntimeError("LLM startup probe failed.") from exc

    if not _stringify_probe_response(response.content):
        raise RuntimeError("LLM startup probe failed: empty response.")


def create_app(config_path: str = "config.yml", cases_root: str | None = None) -> FastAPI:
    context = build_runtime_context(config_path)
    service = RuntimeService(context)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _probe_llm_backend(context.config)
        yield

    app = FastAPI(title="support-ope-agents API", version="0.1.0", lifespan=lifespan)
    base_dir = Path(config_path).resolve().parent
    default_cases_root = Path(cases_root).expanduser().resolve() if cases_root else base_dir / "work" / "cases"

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

    def is_backend_failure(exc: Exception) -> bool:
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        message = str(exc).lower()
        markers = (
            "llm",
            "openai",
            "api connection",
            "connection failed",
            "deepagents",
            "backend failure",
            "timed out",
        )
        return any(marker in message for marker in markers)

    def map_error(exc: Exception) -> HTTPException:
        if isinstance(exc, FileNotFoundError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, NotADirectoryError | IsADirectoryError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        if is_backend_failure(exc):
            return HTTPException(status_code=500, detail=f"LLM/DeepAgents backend failure: {exc}")
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

    def resolve_raw_media_type(target: Path) -> str:
        suffix = target.suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "text/markdown"
        guessed_mime, _ = mimetypes.guess_type(target.name)
        if guessed_mime:
            return guessed_mime
        if suffix in {".yml", ".yaml"}:
            return "application/yaml"
        return "application/octet-stream"

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ui-config", response_model=UiConfigResponse)
    def get_ui_config() -> UiConfigResponse:
        interfaces = context.config.interfaces
        return UiConfigResponse(
            app_name=interfaces.ui_app_name,
            target_label=interfaces.ui_target_label,
            target_description=interfaces.ui_target_description,
            auth_required=interfaces.auth_required,
            knowledge_sources=[
                UiConfigResponse.DocumentSourceRoute(name=source.name, path=str(source.path))
                for source in context.config.agents.KnowledgeRetrieverAgent.document_sources
            ],
            policy_sources=[
                UiConfigResponse.DocumentSourceRoute(name=source.name, path=str(source.path))
                for source in context.config.agents.ComplianceReviewerAgent.document_sources
            ],
        )

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
        return ChatHistoryResponse.model_validate(
            {
                "case_id": case_id,
                "workspace_path": resolved_workspace,
                "messages": messages,
                "conversation_messages": extract_serialized_messages_from_history(messages),
            }
        )

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
        return FileResponse(
            path=target,
            media_type=resolve_raw_media_type(target),
            headers={"Content-Disposition": f'inline; filename="{target.name}"'},
        )

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

    @app.post("/cases/{case_id}/report", response_model=GenerateReportResponse)
    def generate_report(
        case_id: str,
        request: GenerateReportRequest,
        _: None = Depends(require_auth),
    ) -> GenerateReportResponse:
        try:
            payload = service.generate_support_improvement_report(
                case_id=case_id,
                trace_id=request.trace_id,
                workspace_path=resolve_workspace_path(case_id, request.workspace_path),
                checklist=request.checklist,
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return GenerateReportResponse.model_validate(payload)

    @app.post("/init-case", response_model=InitCaseResponse)
    def init_case(request: InitCaseRequest, _: None = Depends(require_auth)) -> InitCaseResponse:
        case_id = service.resolve_case_id(prompt=request.prompt, workspace_path=request.workspace_path)
        case_path = service.initialize_case(case_id, workspace_path=request.workspace_path)
        return InitCaseResponse(
            case_id=case_id,
            case_path=str(case_path),
            case_title=derive_case_title(request.prompt, fallback=case_id),
        )

    @app.post("/describe-agents")
    def describe_agents(request: DescribeAgentsRequest, _: None = Depends(require_auth)) -> list[dict[str, object]]:
        case_id = service.resolve_case_id(prompt=request.prompt)
        try:
            return service.describe_agents(case_id)
        except Exception as exc:
            raise map_error(exc) from exc

    @app.get("/control-catalog")
    def describe_control_catalog(_: None = Depends(require_auth)) -> dict[str, object]:
        return service.describe_control_catalog()

    @app.get("/cases/{case_id}/runtime-audit")
    def describe_runtime_audit(
        case_id: str,
        workspace_path: str | None = None,
        trace_id: str = Query(...),
        _: None = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return service.describe_runtime_audit(
                case_id=case_id,
                trace_id=trace_id,
                workspace_path=resolve_workspace_path(case_id, workspace_path),
            )
        except Exception as exc:
            raise map_error(exc) from exc

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
        try:
            result = service.action(
                prompt=request.prompt,
                case_id=request.case_id,
                workspace_path=request.workspace_path,
                trace_id=request.trace_id,
                execution_plan=request.execution_plan,
                external_ticket_id=request.external_ticket_id,
                internal_ticket_id=request.internal_ticket_id,
                conversation_messages=[message.model_dump() for message in request.conversation_messages],
            )
        except Exception as exc:
            raise map_error(exc) from exc
        return RuntimeEnvelope.model_validate(result)

    @app.post("/resume-customer-input", response_model=RuntimeEnvelope)
    def resume_customer_input(request: ResumeCustomerInputRequest, _: None = Depends(require_auth)) -> RuntimeEnvelope:
        try:
            result = service.resume_customer_input(
                case_id=request.case_id,
                trace_id=request.trace_id,
                workspace_path=request.workspace_path,
                additional_input=request.additional_input,
                answer_key=request.answer_key,
                external_ticket_id=request.external_ticket_id,
                internal_ticket_id=request.internal_ticket_id,
            )
        except Exception as exc:
            raise map_error(exc) from exc
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


def _prepare_effective_config(config_path: Path, manifest_override: str) -> Path:
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    section = raw.setdefault("support_ope_agents", {})
    tools = section.setdefault("tools", {})
    logical_tools = tools.setdefault("logical_tools", {})
    manifest_path = manifest_override or tools.get("mcp_manifest_path") or ""

    if manifest_path:
        tools["mcp_manifest_path"] = manifest_path
        return config_path

    for tool_name in ("external_ticket", "internal_ticket"):
        tool_settings = logical_tools.get(tool_name)
        if isinstance(tool_settings, dict):
            tool_settings["enabled"] = False

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yml", delete=False) as temp_handle:
        yaml.safe_dump(raw, temp_handle, allow_unicode=True, sort_keys=False)
        effective_config_path = Path(temp_handle.name)

    print("MCP manifest was not configured. Starting with ticket MCP tools disabled for UI testing.")
    return effective_config_path


def main() -> int:
    config_path = Path(os.environ.get("SUPPORT_OPE_SAMPLE_CONFIG", "config.yml")).expanduser().resolve()
    manifest_override = os.environ.get("SUPPORT_OPE_SAMPLE_MCP_MANIFEST_PATH", "").strip()
    cases_root = os.environ.get("SUPPORT_OPE_SAMPLE_CASES_ROOT")
    host = os.environ.get("SUPPORT_OPE_SAMPLE_HOST") or os.environ.get("HOST") or DEFAULT_API_HOST
    port_value = os.environ.get("SUPPORT_OPE_SAMPLE_PORT") or os.environ.get("PORT") or str(DEFAULT_API_PORT)

    effective_config_path = _prepare_effective_config(config_path, manifest_override)
    app = create_app(str(effective_config_path), cases_root=cases_root)
    uvicorn.run(app, host=host, port=int(port_value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())