from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_DOCUMENT_IGNORE_PATTERNS = [
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

DEFAULT_POLICY_SEARCH_KEYWORDS = [
    "規定",
    "ガイドライン",
    "法令",
    "注意",
    "免責",
    "生成AI",
]


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmSettings(StrictConfigModel):
    provider: str
    model: str
    api_key: str
    base_url: str | None = None


class ConfigPathSettings(StrictConfigModel):
    instructions_path: Path | None = None


class DataPathSettings(StrictConfigModel):
    shared_memory_subdir: str = ".memory"
    artifacts_subdir: str = ".artifacts"
    evidence_subdir: str = ".evidence"
    report_subdir: str = ".report"
    trace_subdir: str = ".traces"
    checkpoint_db_filename: str = "checkpoints.sqlite"


class EscalationSettings(StrictConfigModel):
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


class WorkflowSettings(StrictConfigModel):
    max_context_chars: int = 12000
    compress_threshold_chars: int = 9000
    approval_node: str = "wait_for_approval"
    auto_compress: bool = True
    max_summary_chars: int = 4000


class TracingSettings(StrictConfigModel):
    enabled: bool = False
    provider: str = "langfuse"
    project_name: str = "support-ope-agents"


class KnowledgeDocumentSource(StrictConfigModel):
    name: str
    description: str
    path: Path


class DocumentSourceSettings(StrictConfigModel):
    document_sources: list[KnowledgeDocumentSource] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=lambda: DEFAULT_DOCUMENT_IGNORE_PATTERNS.copy())
    ignore_patterns_file: Path | None = None


class ComplianceNoticeSettings(StrictConfigModel):
    required: bool = False
    required_phrases: list[str] = Field(
        default_factory=lambda: [
            "生成AIは誤った回答をすることがあります",
            "生成AIは誤った回答を含む可能性があります",
            "AI generated responses may contain mistakes",
        ]
    )


class KnowledgeRetrievalSettings(DocumentSourceSettings):
    pass


class IntakePiiMaskSettings(StrictConfigModel):
    enabled: bool = False


ConstraintMode = Literal["default", "instruction_only", "runtime_only", "bypass"]
KnowledgeSearchStrategy = Literal["deepagents", "hybrid", "backend_only"]


class IntakeAgentSettings(StrictConfigModel):
    enabled: bool = True
    max_context_chars: int | None = None
    compress_threshold_chars: int | None = None
    auto_compress: bool = True
    model: str | None = None
    constraint_mode: ConstraintMode | None = None
    pii_mask: IntakePiiMaskSettings = Field(default_factory=IntakePiiMaskSettings)


class AgentSettings(StrictConfigModel):
    enabled: bool = True
    max_context_chars: int | None = None
    compress_threshold_chars: int | None = None
    auto_compress: bool = True
    model: str | None = None
    constraint_mode: ConstraintMode | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRetrieverAgentSettings(AgentSettings):
    document_sources: list[KnowledgeDocumentSource] = Field(default_factory=list)
    search_strategy: KnowledgeSearchStrategy = "hybrid"
    result_mode: Literal["relaxed", "raw_backend"] = "relaxed"
    backend_read_char_limit: int | None = 8000
    max_evidence_count: int = 3
    candidate_path_limit: int = 5
    persist_raw_search_snapshot: bool = False


class InvestigateAgentSettings(KnowledgeRetrieverAgentSettings):
    pass


class ComplianceReviewerAgentSettings(AgentSettings):
    document_sources: list[KnowledgeDocumentSource] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=lambda: DEFAULT_DOCUMENT_IGNORE_PATTERNS.copy())
    ignore_patterns_file: Path | None = None
    policy_keywords: list[str] = Field(default_factory=lambda: DEFAULT_POLICY_SEARCH_KEYWORDS.copy())
    policy_keyword_expansion_enabled: bool = False
    policy_keyword_expansion_count: int = 12
    max_evidence_count: int = 3
    candidate_path_limit: int = 5
    backend_read_char_limit: int | None = 8000
    summary_max_chars: int | None = 600
    extraction_mode: Literal["limited", "relaxed", "raw_backend"] = "limited"
    raw_backend_max_matches: int | None = 50
    notice: ComplianceNoticeSettings = Field(default_factory=ComplianceNoticeSettings)
    max_review_loops: int = 3


class SupervisorAgentSettings(AgentSettings):
    auto_generate_report: bool = False
    max_investigation_loops: int = Field(default=1, ge=0, le=5)
    report_on: list[Literal["waiting_approval", "closed"]] = Field(default_factory=lambda: ["waiting_approval"])

    @field_validator("report_on", mode="before")
    @classmethod
    def _coerce_report_on(cls, value: object) -> object:
        if isinstance(value, str):
            return [value]
        return value


class BackSupportEscalationAgentSettings(AgentSettings):
    escalation: EscalationSettings = Field(default_factory=EscalationSettings)


class ObjectiveEvaluationAgentSettings(AgentSettings):
    pass_score: int = 80
    missing_shared_memory_penalty: int = 12
    missing_agent_memory_penalty: int = 8
    private_memory_penalty: int = 5
    agent_error_penalty: int = 15
    primary_failure_penalty: int = 35


class AgentCatalogSettings(StrictConfigModel):
    default_constraint_mode: ConstraintMode | None = None
    SuperVisorAgent: SupervisorAgentSettings = Field(default_factory=SupervisorAgentSettings)
    ObjectiveEvaluationAgent: ObjectiveEvaluationAgentSettings = Field(default_factory=ObjectiveEvaluationAgentSettings)
    IntakeAgent: IntakeAgentSettings = Field(default_factory=IntakeAgentSettings)
    InvestigateAgent: InvestigateAgentSettings = Field(default_factory=InvestigateAgentSettings)
    LogAnalyzerAgent: AgentSettings = Field(default_factory=AgentSettings)
    KnowledgeRetrieverAgent: KnowledgeRetrieverAgentSettings = Field(default_factory=KnowledgeRetrieverAgentSettings)
    DraftWriterAgent: AgentSettings = Field(default_factory=AgentSettings)
    ComplianceReviewerAgent: ComplianceReviewerAgentSettings = Field(default_factory=ComplianceReviewerAgentSettings)
    BackSupportEscalationAgent: BackSupportEscalationAgentSettings = Field(default_factory=BackSupportEscalationAgentSettings)
    BackSupportInquiryWriterAgent: AgentSettings = Field(default_factory=AgentSettings)
    ApprovalAgent: AgentSettings = Field(default_factory=AgentSettings)
    TicketUpdateAgent: AgentSettings = Field(default_factory=AgentSettings)

    def get(
        self, role: str
    ) -> AgentSettings | IntakeAgentSettings | InvestigateAgentSettings | KnowledgeRetrieverAgentSettings | ComplianceReviewerAgentSettings | SupervisorAgentSettings | BackSupportEscalationAgentSettings | ObjectiveEvaluationAgentSettings | None:
        return getattr(self, role, None)

    @model_validator(mode="after")
    def _backfill_investigate_settings(self) -> "AgentCatalogSettings":
        if self.InvestigateAgent.document_sources:
            return self
        legacy = self.KnowledgeRetrieverAgent
        has_legacy_override = bool(legacy.document_sources) or legacy.search_strategy != "hybrid" or legacy.result_mode != "relaxed"
        if not has_legacy_override:
            return self
        self.InvestigateAgent = InvestigateAgentSettings.model_validate(legacy.model_dump())
        return self

    def resolve_constraint_mode(self, role: str, *, fallback: ConstraintMode = "default") -> ConstraintMode:
        settings = self.get(role)
        explicit = getattr(settings, "constraint_mode", None) if settings is not None else None
        if explicit:
            return cast(ConstraintMode, explicit)
        if self.default_constraint_mode:
            return self.default_constraint_mode
        return fallback


class McpToolBinding(StrictConfigModel):
    type: Literal["mcp"] = "mcp"
    server: str
    tool: str


class BuiltinToolBinding(StrictConfigModel):
    type: Literal["builtin"] = "builtin"
    tool: str | None = None


class DisabledToolBinding(StrictConfigModel):
    type: Literal["disabled"] = "disabled"


ToolBinding = BuiltinToolBinding | McpToolBinding | DisabledToolBinding


class LogicalToolSettings(StrictConfigModel):
    enabled: bool = True
    provider: Literal["builtin", "mcp"] = "builtin"
    builtin_tool: str | None = None
    server: str | None = None
    tool: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def _validate_enabled_provider(self) -> "LogicalToolSettings":
        if not self.enabled:
            return self
        if self.provider == "mcp":
            if not self.server or not self.tool:
                raise ValueError("enabled logical tool with provider='mcp' requires both 'server' and 'tool'")
            return self
        if self.server or self.tool:
            raise ValueError("logical tool with provider='builtin' cannot define 'server' or 'tool'")
        return self


class ToolSettings(StrictConfigModel):
    mcp_manifest_path: Path | None = None
    mcp_timeout_seconds: float = 30.0
    download_timeout_seconds: float = 30.0
    analysis_max_chars: int = 16000
    libreoffice_command: str | None = None
    logical_tools: dict[str, LogicalToolSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_mcp_manifest_requirement(self) -> "ToolSettings":
        if self.has_enabled_mcp_tools() and self.mcp_manifest_path is None:
            raise ValueError("tools.mcp_manifest_path is required when any enabled logical tool uses provider='mcp'")
        return self

    def has_enabled_mcp_tools(self) -> bool:
        return any(tool.enabled and tool.provider == "mcp" for tool in self.logical_tools.values())

    def get_logical_tool(self, name: str) -> LogicalToolSettings | None:
        return self.logical_tools.get(name)


class InterfaceSettings(StrictConfigModel):
    enable_cli: bool = True
    enable_api: bool = False
    enable_mcp: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    ui_app_name: str = "Support Desk"
    ui_target_label: str | None = None
    ui_target_description: str | None = None
    cors_allowed_origins: list[str] = Field(default_factory=list)
    auth_required: bool = False
    auth_token: str | None = None
    auth_header_name: str = "X-Support-Ope-Token"
    mcp_transport: str = "streamable-http"

    @model_validator(mode="after")
    def _validate_auth_requirement(self) -> "InterfaceSettings":
        if self.auth_required and not self.auth_token:
            raise ValueError("interfaces.auth_token is required when interfaces.auth_required is true")
        return self


class AppConfig(StrictConfigModel):
    llm: LlmSettings
    config_paths: ConfigPathSettings
    data_paths: DataPathSettings
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    tools: ToolSettings = Field(default_factory=ToolSettings)
    interfaces: InterfaceSettings = Field(default_factory=InterfaceSettings)
    agents: AgentCatalogSettings = Field(default_factory=AgentCatalogSettings)

    @model_validator(mode="after")
    def _validate_llm_requirement(self) -> "AppConfig":
        if self.llm.provider.lower() != "openai":
            raise ValueError("llm.provider must be 'openai'")
        api_key = str(self.llm.api_key or "").strip()
        if not api_key:
            raise ValueError("llm.api_key is required and must not be empty")
        if api_key.lower() in {"dummy", "test", "placeholder"}:
            raise ValueError("llm.api_key must not use placeholder values such as dummy, test, or placeholder")
        return self