from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    name: str
    environment: str = "local"


class LlmSettings(BaseModel):
    provider: str
    model: str
    api_key: str


class PathSettings(BaseModel):
    workspace_root: Path
    instructions_root: Path
    shared_memory_subdir: str = "memory"
    instruction_override_subdir: str = "overrides"
    artifacts_subdir: str = "artifacts"
    evidence_subdir: str = "evidence"
    workspace_manifest_filename: str = "workspace.json"


class WorkflowSettings(BaseModel):
    max_context_chars: int = 12000
    compress_threshold_chars: int = 9000
    approval_node: str = "wait_for_approval"
    auto_compress: bool = True
    max_summary_chars: int = 4000


class TracingSettings(BaseModel):
    enabled: bool = False
    provider: str = "langsmith"
    project_name: str = "support-ope-agents"


class McpToolBinding(BaseModel):
    type: Literal["mcp"] = "mcp"
    server: str
    tool: str


class ToolSettings(BaseModel):
    enable_zendesk: bool = False
    enable_redmine: bool = False
    enable_knowledge_base: bool = False
    enable_python_analysis: bool = True
    mcp_manifest_path: Path | None = None
    mcp_timeout_seconds: float = 30.0
    overrides: dict[str, dict[str, McpToolBinding]] = Field(default_factory=dict)

    def has_overrides(self) -> bool:
        return any(self.overrides.values())


class InterfaceSettings(BaseModel):
    enable_cli: bool = True
    enable_api: bool = False
    enable_mcp: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    mcp_transport: str = "streamable-http"


class AgentSettings(BaseModel):
    enabled: bool = True
    max_context_chars: int | None = None
    compress_threshold_chars: int | None = None
    auto_compress: bool = True
    model: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AppConfig(BaseModel):
    app: AppSettings
    llm: LlmSettings
    paths: PathSettings
    workflow: WorkflowSettings
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    interfaces: InterfaceSettings = Field(default_factory=InterfaceSettings)
    agents: dict[str, AgentSettings] = Field(default_factory=dict)