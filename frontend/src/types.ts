export type CaseSummary = {
  case_id: string;
  case_title: string;
  workspace_path: string;
  updated_at: string;
  message_count: number;
};

export type ChatMessage = {
  role: string;
  content: string;
  trace_id?: string | null;
  event?: string | null;
  created_at?: string | null;
};

export type ChatHistoryResponse = {
  case_id: string;
  workspace_path: string;
  messages: ChatMessage[];
};

export type WorkspaceEntry = {
  name: string;
  path: string;
  kind: 'file' | 'directory' | string;
  size?: number | null;
  updated_at?: string | null;
};

export type WorkspaceBrowseResponse = {
  case_id: string;
  workspace_path: string;
  current_path: string;
  entries: WorkspaceEntry[];
};

export type WorkspaceFileResponse = {
  case_id: string;
  workspace_path: string;
  path: string;
  name: string;
  mime_type?: string | null;
  preview_available: boolean;
  truncated: boolean;
  content?: string | null;
};

export type WorkspaceUploadResponse = {
  case_id: string;
  workspace_path: string;
  path: string;
  size: number;
};

export type UiConfigResponse = {
  app_name: string;
  target_label?: string | null;
  target_description?: string | null;
  auth_required: boolean;
};

export type RuntimeEnvelope = {
  case_id: string;
  trace_id?: string | null;
  workflow_kind?: string | null;
  workflow_label?: string | null;
  execution_mode?: string | null;
  external_ticket_id?: string | null;
  internal_ticket_id?: string | null;
  plan_summary?: string | null;
  plan_steps: string[];
  requires_approval?: boolean | null;
  requires_customer_input?: boolean | null;
  state: Record<string, unknown>;
};

export type GenerateReportResponse = {
  case_id: string;
  trace_id: string;
  report_path: string;
  sequence_diagram: string;
};

export type ControlCatalogResponse = {
  summary: {
    agent_count: number;
    workflow_node_count: number;
    workflow_edge_count: number;
    logical_tool_count: number;
    instruction_role_count: number;
    control_point_count: number;
  };
};

export type RuntimeAuditDecision = {
  control_point_id: string;
  category: string;
  outcome: string;
  detail: string;
};

export type RuntimeAuditResponse = {
  summary: {
    case_id: string;
    trace_id: string;
    status: string;
    execution_mode: string;
    workflow_kind: string;
    result: string;
    approval_route: string;
    used_role_count: number;
    decision_count: number;
    draft_review_iterations: number;
  };
  workflow_path: string[];
  used_roles: string[];
  decision_log: RuntimeAuditDecision[];
};

export type InitCaseResponse = {
  case_id: string;
  case_title: string;
  case_path: string;
};