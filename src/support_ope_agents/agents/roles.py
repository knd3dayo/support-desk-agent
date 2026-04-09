from __future__ import annotations

SUPERVISOR_AGENT = "SuperVisorAgent"
INTAKE_AGENT = "IntakeAgent"
LOG_ANALYZER_AGENT = "LogAnalyzerAgent"
KNOWLEDGE_RETRIEVER_AGENT = "KnowledgeRetrieverAgent"
RESOLUTION_AGENT = "ResolutionAgent"
DRAFT_WRITER_AGENT = "DraftWriterAgent"
COMPLIANCE_REVIEWER_AGENT = "ComplianceReviewerAgent"
APPROVAL_AGENT = "ApprovalAgent"
TICKET_UPDATE_AGENT = "TicketUpdateAgent"

LEGACY_ROLE_ALIASES: dict[str, str] = {
    "intake_supervisor": INTAKE_AGENT,
    "log_analyzer": LOG_ANALYZER_AGENT,
    "LogAnalyzerSpecialist": LOG_ANALYZER_AGENT,
    "knowledge_retriever": KNOWLEDGE_RETRIEVER_AGENT,
    "KnowledgeRetrieverSpecialist": KNOWLEDGE_RETRIEVER_AGENT,
    "resolution_supervisor": RESOLUTION_AGENT,
    "draft_writer": DRAFT_WRITER_AGENT,
    "DraftWriterSpecialist": DRAFT_WRITER_AGENT,
    "compliance_reviewer": COMPLIANCE_REVIEWER_AGENT,
    "ComplianceReviewerSpecialist": COMPLIANCE_REVIEWER_AGENT,
    "ticket_update": TICKET_UPDATE_AGENT,
}

LEGACY_FILE_NAMES: dict[str, tuple[str, ...]] = {
    INTAKE_AGENT: ("intake_supervisor",),
    LOG_ANALYZER_AGENT: ("LogAnalyzerSpecialist", "log_analyzer"),
    KNOWLEDGE_RETRIEVER_AGENT: ("KnowledgeRetrieverSpecialist", "knowledge_retriever"),
    RESOLUTION_AGENT: ("resolution_supervisor",),
    DRAFT_WRITER_AGENT: ("DraftWriterSpecialist", "draft_writer"),
    COMPLIANCE_REVIEWER_AGENT: ("ComplianceReviewerSpecialist", "compliance_reviewer"),
    TICKET_UPDATE_AGENT: ("ticket_update",),
}

DEFAULT_AGENT_ROLES: tuple[str, ...] = (
    SUPERVISOR_AGENT,
    INTAKE_AGENT,
    LOG_ANALYZER_AGENT,
    KNOWLEDGE_RETRIEVER_AGENT,
    RESOLUTION_AGENT,
    DRAFT_WRITER_AGENT,
    COMPLIANCE_REVIEWER_AGENT,
    APPROVAL_AGENT,
    TICKET_UPDATE_AGENT,
)


def canonical_role(role: str) -> str:
    return LEGACY_ROLE_ALIASES.get(role, role)


def candidate_role_names(role: str) -> tuple[str, ...]:
    canonical = canonical_role(role)
    legacy_names = LEGACY_FILE_NAMES.get(canonical, ())
    return (canonical, *legacy_names)