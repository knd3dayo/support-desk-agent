from __future__ import annotations

from pathlib import Path

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


class WorkflowSettings(BaseModel):
    max_context_chars: int = 12000
    compress_threshold_chars: int = 9000
    approval_node: str = "wait_for_approval"


class TracingSettings(BaseModel):
    enabled: bool = False
    provider: str = "langsmith"
    project_name: str = "support-ope-agents"


class ToolSettings(BaseModel):
    enable_zendesk: bool = False
    enable_redmine: bool = False
    enable_knowledge_base: bool = False
    enable_python_analysis: bool = True


class AppConfig(BaseModel):
    app: AppSettings
    llm: LlmSettings
    paths: PathSettings
    workflow: WorkflowSettings
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)