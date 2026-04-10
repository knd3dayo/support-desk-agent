from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class LlmSettings(BaseModel):
    provider: str
    model: str
    api_key: str
    base_url: str | None = None


class ConfigPathSettings(BaseModel):
    instructions_path: Path | None = None


class DataPathSettings(BaseModel):
    shared_memory_subdir: str = ".memory"
    artifacts_subdir: str = ".artifacts"
    evidence_subdir: str = ".evidence"


class EscalationSettings(BaseModel):
    uncertainty_markers: list[str] = Field(
        default_factory=lambda: [
            "未解決",
            "不明",
            "特定でき",
            "確証",
            "追加ログ",
            "need more logs",
            "unable to conclude",
            "insufficient evidence",
        ]
    )
    missing_log_markers: list[str] = Field(default_factory=lambda: ["ログファイルが見つからなかった"])
    default_missing_artifacts_by_workflow: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "incident_investigation": [
                "発生時刻前後のアプリケーションログ",
                "再現手順または実施操作",
            ],
            "specification_inquiry": [
                "関連仕様書または設定値",
                "期待動作と実際の動作差分",
            ],
            "ambiguous_case": [
                "発生条件を示す追加ログ",
                "期待動作と実際の動作差分",
            ],
        }
    )


class WorkflowSettings(BaseModel):
    max_context_chars: int = 12000
    compress_threshold_chars: int = 9000
    approval_node: str = "wait_for_approval"
    auto_compress: bool = True
    max_summary_chars: int = 4000
    escalation: EscalationSettings = Field(default_factory=EscalationSettings)


class TracingSettings(BaseModel):
    enabled: bool = False
    provider: str = "langsmith"
    project_name: str = "support-ope-agents"


class KnowledgeDocumentSource(BaseModel):
    name: str
    description: str
    path: Path


class TicketSourceSettings(BaseModel):
    description: str = ""
    mcp_server: str | None = None
    mcp_tool: str | None = None


class KnowledgeRetrievalSettings(BaseModel):
    document_sources: list[KnowledgeDocumentSource] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(
        default_factory=lambda: [
            ".*",
            "**/.*",
            ".*/**",
            "**/.*/**",
            "node_modules/**",
            "**/node_modules/**",
            ".venv/**",
            "**/.venv/**",
            "venv/**",
            "**/venv/**",
            "site-packages/**",
            "**/site-packages/**",
            ".pytest_cache/**",
            "**/.pytest_cache/**",
            "__pycache__/**",
            "**/__pycache__/**",
            "build/**",
            "**/build/**",
            "dist/**",
            "**/dist/**",
        ]
    )
    ignore_patterns_file: Path | None = None
    external_ticket: TicketSourceSettings = Field(default_factory=TicketSourceSettings)
    internal_ticket: TicketSourceSettings = Field(default_factory=TicketSourceSettings)


class IntakePiiMaskSettings(BaseModel):
    enabled: bool = False


class IntakeSettings(BaseModel):
    pii_mask: IntakePiiMaskSettings = Field(default_factory=IntakePiiMaskSettings)


class McpToolBinding(BaseModel):
    type: Literal["mcp"] = "mcp"
    server: str
    tool: str


class BuiltinToolBinding(BaseModel):
    type: Literal["builtin"] = "builtin"
    tool: str | None = None


class DisabledToolBinding(BaseModel):
    type: Literal["disabled"] = "disabled"


ToolBinding = BuiltinToolBinding | McpToolBinding | DisabledToolBinding


class ToolSettings(BaseModel):
    enable_zendesk: bool = False
    enable_redmine: bool = False
    enable_knowledge_base: bool = False
    enable_python_analysis: bool = True
    mcp_manifest_path: Path | None = None
    mcp_timeout_seconds: float = 30.0
    download_timeout_seconds: float = 30.0
    analysis_max_chars: int = 16000
    libreoffice_command: str | None = None
    overrides: dict[str, dict[str, ToolBinding]] = Field(default_factory=dict)

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
    llm: LlmSettings
    config_paths: ConfigPathSettings
    data_paths: DataPathSettings
    intake: IntakeSettings = Field(default_factory=IntakeSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    knowledge_retrieval: KnowledgeRetrievalSettings = Field(default_factory=KnowledgeRetrievalSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    interfaces: InterfaceSettings = Field(default_factory=InterfaceSettings)
    agents: dict[str, AgentSettings] = Field(default_factory=dict)