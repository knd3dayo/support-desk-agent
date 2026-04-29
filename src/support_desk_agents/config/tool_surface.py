from __future__ import annotations

INTERNAL_ONLY_LOGICAL_TOOLS = frozenset(
    {
        "detect_log_format",
        "extract_log_time_range",
        "infer_log_header_pattern",
        "read_shared_memory",
        "write_draft",
        "write_shared_memory",
        "write_working_memory",
    }
)

CONFIGURABLE_LOGICAL_TOOLS = frozenset(
    {
        "classify_ticket",
        "evaluate_agent_result",
        "external_ticket",
        "inspect_workflow_state",
        "internal_ticket",
        "pii_mask",
        "prepare_ticket_update",
        "read_log_file",
        "record_approval_decision",
        "redmine_update",
        "route_phase_agent",
        "run_python_analysis",
        "scan_workspace_artifacts",
        "search_documents",
        "spawn_back_support_escalation_agent",
        "spawn_back_support_inquiry_writer_agent",
        "spawn_draft_writer_agent",
        "spawn_investigate_agent",
        "spawn_knowledge_retriever_agent",
        "spawn_log_analyzer_agent",
        "zendesk_reply",
    }
)

MCP_OVERRIDEABLE_LOGICAL_TOOLS = CONFIGURABLE_LOGICAL_TOOLS