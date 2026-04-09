from __future__ import annotations

SUPERVISOR_AGENT = "SuperVisorAgent"
INTAKE_AGENT = "IntakeAgent"
INVESTIGATION_AGENT = "InvestigationAgent"
LOG_ANALYZER_SPECIALIST = "LogAnalyzerSpecialist"
KNOWLEDGE_RETRIEVER_SPECIALIST = "KnowledgeRetrieverSpecialist"
RESOLUTION_AGENT = "ResolutionAgent"
DRAFT_WRITER_SPECIALIST = "DraftWriterSpecialist"
COMPLIANCE_REVIEWER_SPECIALIST = "ComplianceReviewerSpecialist"
APPROVAL_AGENT = "ApprovalAgent"
TICKET_UPDATE_AGENT = "TicketUpdateAgent"

LEGACY_ROLE_ALIASES: dict[str, str] = {
    "intake_supervisor": INTAKE_AGENT,
    "investigation_supervisor": INVESTIGATION_AGENT,
    "log_analyzer": LOG_ANALYZER_SPECIALIST,
    "knowledge_retriever": KNOWLEDGE_RETRIEVER_SPECIALIST,
    "resolution_supervisor": RESOLUTION_AGENT,
    "draft_writer": DRAFT_WRITER_SPECIALIST,
    "compliance_reviewer": COMPLIANCE_REVIEWER_SPECIALIST,
    "ticket_update": TICKET_UPDATE_AGENT,
}

LEGACY_FILE_NAMES: dict[str, tuple[str, ...]] = {
    INTAKE_AGENT: ("intake_supervisor",),
    INVESTIGATION_AGENT: ("investigation_supervisor",),
    LOG_ANALYZER_SPECIALIST: ("log_analyzer",),
    KNOWLEDGE_RETRIEVER_SPECIALIST: ("knowledge_retriever",),
    RESOLUTION_AGENT: ("resolution_supervisor",),
    DRAFT_WRITER_SPECIALIST: ("draft_writer",),
    COMPLIANCE_REVIEWER_SPECIALIST: ("compliance_reviewer",),
    TICKET_UPDATE_AGENT: ("ticket_update",),
}

DEFAULT_AGENT_ROLES: tuple[str, ...] = (
    SUPERVISOR_AGENT,
    INTAKE_AGENT,
    INVESTIGATION_AGENT,
    LOG_ANALYZER_SPECIALIST,
    KNOWLEDGE_RETRIEVER_SPECIALIST,
    RESOLUTION_AGENT,
    DRAFT_WRITER_SPECIALIST,
    COMPLIANCE_REVIEWER_SPECIALIST,
    APPROVAL_AGENT,
    TICKET_UPDATE_AGENT,
)


def canonical_role(role: str) -> str:
    return LEGACY_ROLE_ALIASES.get(role, role)


def candidate_role_names(role: str) -> tuple[str, ...]:
    canonical = canonical_role(role)
    legacy_names = LEGACY_FILE_NAMES.get(canonical, ())
    return (canonical, *legacy_names)